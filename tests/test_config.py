"""設定の読み書き。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hph.config import Config, ConfigError


def test_defaults_applied_for_missing_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": 9000}), encoding="utf-8")
    config = Config.load(path)
    assert config.port == 9000
    assert config.include_extensions == [".html", ".htm", ".xhtml"]


def test_roots_accept_string_and_object(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    raw = {"roots": [str(tmp_path / "a"), {"path": str(tmp_path / "a"), "name": "dup"}]}
    config = Config.from_dict(raw)
    assert len(config.roots) == 1  # 同じパスは重複排除される


def test_add_missing_root_raises(tmp_path: Path) -> None:
    config = Config.from_dict({})
    with pytest.raises(ConfigError):
        config.add_root(tmp_path / "does-not-exist")


def test_save_and_reload_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    config = Config.from_dict({})
    config.path = tmp_path / "config.json"
    config.add_root(tmp_path / "docs", "ドキュメント")
    config.save()
    reloaded = Config.load(config.path)
    assert [r.name for r in reloaded.roots] == ["ドキュメント"]


def test_invalid_json_reports_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(path)


def test_extensions_are_normalised() -> None:
    config = Config.from_dict({"include_extensions": ["HTML", ".Htm", ""]})
    assert config.include_extensions == [".html", ".htm"]
