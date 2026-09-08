"""LaTeX コンパイルをバックグラウンドジョブとして実行・追跡する。

プレビューを開いたまま待たなくてもコンパイルは進み、別のファイルへ切り替えても
中断されない。同じファイルへの要求は 1 本のジョブへ相乗りさせ、異なるファイルは
:data:`MAX_CONCURRENT` の範囲で並列に走らせる。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .tex import CompileResult, compile_tex

#: 同時に走らせる LaTeX プロセスの上限（1 コンパイル ≒ 1 コアを使い切るため控えめにする）。
MAX_CONCURRENT = max(1, min(4, (os.cpu_count() or 2) // 2))
#: 完了したジョブを保持する時間（秒）。ポーリングを取りこぼしても結果を拾えるようにする。
RETENTION_SECONDS = 300.0
#: 保持するジョブの最大件数（完了済みのものから捨てる）。
MAX_JOBS = 64
#: 応答を返す前に完了を待ってみる時間（キャッシュ済みなら 1 往復で終わらせる）。
SETTLE_SECONDS = 0.4


@dataclass
class TexJob:
    """1 ファイル分のコンパイルジョブ。"""

    file_id: str
    task: asyncio.Task[CompileResult]
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def running(self) -> bool:
        """まだ実行中か。"""
        return not self.task.done()

    @property
    def elapsed_ms(self) -> float:
        """開始からの経過時間（ミリ秒）。完了後はかかった時間で止まる。"""
        end = time.monotonic() if self.finished_at is None else self.finished_at
        return (end - self.started_at) * 1000

    def mark_finished(self) -> None:
        """完了時刻を記録する（経過時間を止めるため）。"""
        if self.finished_at is None:
            self.finished_at = time.monotonic()

    def result(self) -> CompileResult:
        """完了済みジョブの結果。中断・異常終了は error として包む。"""
        if self.task.cancelled():
            return CompileResult(status="error", message="コンパイルは中断されました")
        exc = self.task.exception()
        if exc is not None:  # pragma: no cover - compile_tex は例外を出さない設計
            return CompileResult(status="error", message=f"コンパイル処理が異常終了しました: {exc}")
        return self.task.result()

    def to_json(self) -> dict[str, Any]:
        """API レスポンス用の辞書へ変換する。"""
        if self.running:
            return {
                "status": "running",
                "message": "コンパイル中です",
                "elapsedMs": round(self.elapsed_ms, 1),
            }
        body = self.result().to_json()
        body["elapsedMs"] = round(self.elapsed_ms, 1)
        return body


class TexJobRegistry:
    """ファイル単位のコンパイルジョブを保持するレジストリ。"""

    def __init__(self, *, max_concurrent: int = MAX_CONCURRENT) -> None:
        """同時実行数の上限を指定して初期化する。"""
        self._jobs: dict[str, TexJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def get(self, file_id: str) -> TexJob | None:
        """ファイル ID に対応するジョブを引く（無ければ None）。"""
        return self._jobs.get(file_id)

    def submit(self, file_id: str, path: Path, config: Config, *, force: bool = False) -> TexJob:
        """コンパイルを開始する。同じファイルが実行中なら、そのジョブへ相乗りする。"""
        existing = self._jobs.get(file_id)
        if existing is not None and existing.running:
            return existing
        self._prune()
        task = asyncio.create_task(
            self._compile(path, config, force=force), name=f"hph-tex:{file_id}"
        )
        job = TexJob(file_id=file_id, task=task)
        task.add_done_callback(lambda _: job.mark_finished())
        self._jobs[file_id] = job
        return job

    async def settle(self, job: TexJob, timeout: float = SETTLE_SECONDS) -> TexJob:
        """短時間だけ完了を待つ。すぐ終わるジョブを 1 往復で返すための待ち合わせ。"""
        with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
            # shield しないと、タイムアウト時に走っているジョブごと打ち切られてしまう。
            await asyncio.wait_for(asyncio.shield(job.task), timeout)
        return job

    async def shutdown(self) -> None:
        """走っているジョブを打ち切る（サーバー終了時）。"""
        for job in self._jobs.values():
            job.task.cancel()
        self._jobs.clear()

    # ------------------------------------------------------------------
    async def _compile(self, path: Path, config: Config, *, force: bool) -> CompileResult:
        """同時実行数を絞りつつ、別スレッドでコンパイルする。"""
        async with self._semaphore:
            return await asyncio.to_thread(compile_tex, path, config, force=force)

    def _prune(self) -> None:
        """保持期間を過ぎた、または上限を超えた完了済みジョブを捨てる。"""
        now = time.monotonic()
        for file_id, job in list(self._jobs.items()):
            finished_at = job.finished_at
            if finished_at is not None and now - finished_at > RETENTION_SECONDS:
                del self._jobs[file_id]
        while len(self._jobs) > MAX_JOBS:
            oldest = next((fid for fid, job in self._jobs.items() if not job.running), None)
            if oldest is None:  # 実行中しか残っていなければ、これ以上は捨てられない
                break
            del self._jobs[oldest]
