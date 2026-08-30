"""パス解決の安全性検証。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hph.config import Root
from hph.paths import PathAccessError, normalise_relative, resolve_within_root


def test_normalise_rejects_parent_traversal() -> None:
    with pytest.raises(PathAccessError):
        normalise_relative("../../etc/passwd")


def test_normalise_rejects_absolute() -> None:
    with pytest.raises(PathAccessError):
        normalise_relative("//etc/passwd/../..")


def test_resolve_within_root(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.html").write_text("<p>x</p>", encoding="utf-8")
    root = Root.create(tmp_path)
    assert resolve_within_root(root, "a/x.html").read_text(encoding="utf-8") == "<p>x</p>"


def test_symlink_escaping_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.html").write_text("secret", encoding="utf-8")
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    (root_dir / "link.html").symlink_to(outside / "secret.html")
    root = Root.create(root_dir)
    with pytest.raises(PathAccessError):
        resolve_within_root(root, "link.html")
