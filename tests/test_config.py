"""設定の読み書き。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hph.config import Config, ConfigError
from hph.rules import ExcludeRule


def test_defaults_applied_for_missing_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": 9000}), encoding="utf-8")
    config = Config.load(path)
    assert config.port == 9000
    assert config.include_extensions == [".html", ".htm", ".xhtml", ".tex"]


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


def test_default_exclude_contains_former_ignore_dirs() -> None:
    config = Config.from_dict({})
    assert ExcludeRule("folder", "equals", "node_modules") in config.exclude


def test_legacy_ignore_dirs_replace_defaults() -> None:
    config = Config.from_dict({"ignore_dirs": ["vendor"]})
    assert config.exclude == (ExcludeRule("folder", "equals", "vendor"),)


def test_legacy_ignore_dirs_merge_into_exclude() -> None:
    raw = {"exclude": [{"target": "file", "match": "suffix", "value": ".bak"}], "ignore_dirs": ["vendor"]}
    config = Config.from_dict(raw)
    assert config.exclude == (
        ExcludeRule("file", "suffix", ".bak"),
        ExcludeRule("folder", "equals", "vendor"),
    )


def test_save_writes_exclude_not_ignore_dirs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    config = Config.from_dict({"ignore_dirs": ["vendor"]})
    config.path = tmp_path / "config.json"
    root = config.add_root(tmp_path / "docs")
    config.update_root(root.id, exclude=(ExcludeRule("folder", "contains", "draft"),))
    config.save()
    saved = json.loads(config.path.read_text(encoding="utf-8"))
    assert "ignore_dirs" not in saved
    assert saved["exclude"] == [{"target": "folder", "match": "equals", "value": "vendor"}]
    assert saved["roots"][0]["exclude"] == [{"target": "folder", "match": "contains", "value": "draft"}]
    reloaded = Config.load(config.path)
    assert reloaded.roots[0].exclude == (ExcludeRule("folder", "contains", "draft"),)


def test_update_root_keeps_name_when_blank(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    config = Config.from_dict({})
    root = config.add_root(tmp_path / "docs", "資料")
    updated = config.update_root(root.id, name="  ")
    assert updated is not None and updated.name == "資料"
    assert config.update_root("missing", name="x") is None


def test_invalid_exclude_in_file_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"exclude": [{"target": "x", "match": "equals", "value": "a"}]}), encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        Config.load(path)
