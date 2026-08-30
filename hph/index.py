"""インデックスの保持・再スキャン・変更通知。

スキャン自体はスレッドプールで実行し、イベントループを止めない。
リビジョン番号が変わったことを ``asyncio.Condition`` で購読者へ通知する。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .scanner import FileEntry, FolderEntry, ScanResult, TitleCache, scan
from .store import UserStore

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """API へ返すインデックスのスナップショット。"""

    revision: int = 0
    files: dict[str, FileEntry] = field(default_factory=dict)
    folders: dict[str, FolderEntry] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    truncated: bool = False
    duration_ms: float = 0.0
    scanned_at: float = 0.0

    def to_json(self, config: Config, store: UserStore) -> dict[str, Any]:
        """API レスポンス用の辞書へ変換する。"""
        state = store.snapshot()
        return {
            "revision": self.revision,
            "scannedAt": self.scanned_at,
            "durationMs": round(self.duration_ms, 2),
            "truncated": self.truncated,
            "errors": self.errors,
            "roots": [
                {
                    "id": root.id,
                    "name": root.name,
                    "path": root.path,
                    "exists": root.exists(),
                    "fileCount": sum(1 for f in self.files.values() if f.root_id == root.id),
                }
                for root in config.roots
            ],
            "folders": [folder.to_json() for folder in self.folders.values()],
            "files": [file.to_json() for file in self.files.values()],
            "stats": {
                "folderCount": len(self.folders),
                "fileCount": len(self.files),
                "maxFiles": config.max_files,
            },
            "userState": state,
        }


class IndexService:
    """スキャン結果を保持し、バックグラウンドで追従させるサービス。"""

    def __init__(self, config: Config, store: UserStore) -> None:
        """設定とユーザー状態を受け取り、空のスナップショットで初期化する。"""
        self.config = config
        self.store = store
        self.snapshot = Snapshot()
        self.scanning = False
        self._cache = TitleCache()
        self._condition = asyncio.Condition()
        self._scan_lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    async def start(self) -> None:
        """初回スキャンを行い、必要ならバックグラウンド監視を開始する。"""
        await self.rescan()
        if self.config.watch_interval_seconds > 0:
            self._watch_task = asyncio.create_task(self._watch_loop(), name="hph-watch")

    async def stop(self) -> None:
        """バックグラウンド監視を停止する。"""
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):  # pragma: no cover - 終了処理
                await self._watch_task
            self._watch_task = None

    # ------------------------------------------------------------------
    async def rescan(self, *, force: bool = False) -> Snapshot:
        """再スキャンする。変更があればリビジョンを進めて通知する。"""
        async with self._scan_lock:
            self.scanning = True
            try:
                result = await asyncio.to_thread(scan, self.config, self._cache)
            except Exception:  # pragma: no cover - 想定外の IO 例外も落とさない
                logger.exception("スキャンに失敗しました")
                self.scanning = False
                return self.snapshot
            finally:
                self.scanning = False
            # `force` でも取り込み自体は必ず行う（設定変更後の反映漏れを防ぐ）。
            changed = self._apply(result)
            if changed or force:
                await self._notify()
            return self.snapshot

    def _apply(self, result: ScanResult) -> bool:
        files = {f.id: f for f in result.files}
        folders = {f.id: f for f in result.folders}
        changed = self._fingerprint(files, folders) != self._fingerprint(
            self.snapshot.files, self.snapshot.folders
        )
        self.snapshot = Snapshot(
            revision=self.snapshot.revision + (1 if changed else 0),
            files=files,
            folders=folders,
            errors=result.errors,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            scanned_at=result.scanned_at,
        )
        if changed:
            self.store.prune(set(files), set(folders))
        return changed

    @staticmethod
    def _fingerprint(files: dict[str, FileEntry], folders: dict[str, FolderEntry]) -> tuple[int, int, int]:
        """内容変化の判定用ハッシュ（件数と更新時刻・サイズの集約）。"""
        signature = 0
        for file in files.values():
            signature ^= hash((file.id, round(file.updated_at, 3), file.size, file.title))
        return (len(files), len(folders), signature)

    # ------------------------------------------------------------------
    async def _watch_loop(self) -> None:
        interval = self.config.watch_interval_seconds
        while True:
            try:
                await asyncio.sleep(interval)
                await self.rescan()
            except asyncio.CancelledError:  # pragma: no cover - 終了処理
                raise
            except Exception:  # pragma: no cover - 監視は止めない
                logger.exception("バックグラウンドスキャンでエラーが発生しました")

    async def _notify(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    async def wait_for_change(self, known_revision: int, timeout: float) -> int | None:
        """リビジョンが `known_revision` から進むまで待つ。タイムアウトで None。"""
        if self.snapshot.revision != known_revision:
            return self.snapshot.revision
        try:
            async with self._condition:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.snapshot.revision != known_revision),
                    timeout=timeout,
                )
        except (asyncio.TimeoutError, TimeoutError):
            return None
        return self.snapshot.revision

    # ------------------------------------------------------------------
    def file(self, file_id: str) -> FileEntry | None:
        """ID からファイルを引く。"""
        return self.snapshot.files.get(file_id)

    def to_json(self) -> dict[str, Any]:
        """現在のインデックスを API レスポンス用の辞書として返す。"""
        payload = self.snapshot.to_json(self.config, self.store)
        payload["scanning"] = self.scanning
        payload["generatedAt"] = time.time()
        return payload
