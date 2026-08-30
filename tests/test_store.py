"""ユーザー状態の永続化。"""

from __future__ import annotations

from pathlib import Path

from hph.store import UserStore


def test_toggle_and_persist(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    assert store.toggle("favorites", "root:a.html") is True
    assert store.toggle("favorites", "root:a.html") is False
    store.toggle("hiddenFolders", "root:dir")
    reloaded = UserStore(tmp_path)
    assert reloaded.snapshot()["hiddenFolders"] == ["root:dir"]


def test_recents_are_deduped_and_capped(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    for i in range(60):
        store.touch_recent(f"file-{i}")
    store.touch_recent("file-5")
    recents = store.snapshot()["recents"]
    assert recents[0] == "file-5"
    assert len(recents) <= 40
    assert len(set(recents)) == len(recents)


def test_broken_state_file_does_not_crash(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text("{ this is not json", encoding="utf-8")
    store = UserStore(tmp_path)
    assert store.snapshot()["favorites"] == []


def test_prune_removes_stale_ids(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    store.toggle("favorites", "gone")
    store.toggle("favorites", "kept")
    store.prune({"kept"}, set())
    assert store.snapshot()["favorites"] == ["kept"]
