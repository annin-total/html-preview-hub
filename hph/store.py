"""お気に入り・非表示フォルダなどのユーザー状態を JSON に永続化する。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

STATE_FILENAME = "state.json"
_EMPTY: dict[str, Any] = {"favorites": [], "hiddenFolders": [], "recents": []}
MAX_RECENTS = 40


class UserStore:
    """スレッドセーフな軽量 KVS（書き込みは原子的に置換）。"""

    def __init__(self, state_dir: Path) -> None:
        """状態ファイルを読み込む（無ければ空の状態で開始する）。"""
        self.path = Path(state_dir) / STATE_FILENAME
        self._lock = threading.Lock()
        self._data = self._read()

    # ------------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {key: list(value) for key, value in _EMPTY.items()}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 壊れた状態ファイルでアプリを止めない（次の保存で上書きされる）。
            return {key: list(value) for key, value in _EMPTY.items()}
        data = {key: list(value) for key, value in _EMPTY.items()}
        if isinstance(raw, dict):
            for key in data:
                value = raw.get(key)
                if isinstance(value, list):
                    data[key] = [str(v) for v in value]
        return data

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, list[str]]:
        """現在の状態のコピーを返す。"""
        with self._lock:
            return {key: list(value) for key, value in self._data.items()}

    def toggle(self, key: str, value: str) -> bool:
        """`key` のリストに `value` を追加/削除する。追加されたら True。"""
        if key not in _EMPTY:
            raise KeyError(key)
        with self._lock:
            items: list[str] = self._data[key]
            if value in items:
                items.remove(value)
                added = False
            else:
                items.append(value)
                added = True
            self._flush()
            return added

    def touch_recent(self, value: str) -> list[str]:
        """最近開いたファイルを先頭に積む（重複排除・上限あり）。"""
        with self._lock:
            recents: list[str] = self._data["recents"]
            if value in recents:
                recents.remove(value)
            recents.insert(0, value)
            del recents[MAX_RECENTS:]
            self._flush()
            return list(recents)

    def prune(self, valid_file_ids: set[str], valid_folder_ids: set[str]) -> None:
        """インデックスに存在しなくなった ID を掃除する。"""
        with self._lock:
            changed = False
            for key, valid in (
                ("favorites", valid_file_ids),
                ("recents", valid_file_ids),
                ("hiddenFolders", valid_folder_ids),
            ):
                kept = [v for v in self._data[key] if v in valid]
                if len(kept) != len(self._data[key]):
                    self._data[key] = kept
                    changed = True
            if changed:
                self._flush()
