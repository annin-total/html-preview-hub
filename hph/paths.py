"""パス解決とディレクトリトラバーサル対策。"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .config import Root


class PathAccessError(Exception):
    """ルート外アクセスなど、許可されないパス参照。"""

    def __init__(self, message: str, status_code: int = 403) -> None:
        """メッセージと、HTTP レスポンスに使うステータスコードを保持する。"""
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalise_relative(rel_path: str) -> PurePosixPath:
    """URL 由来の相対パスを正規化する。`..` や絶対パスは拒否する。"""
    candidate = PurePosixPath(rel_path.strip().lstrip("/"))
    if candidate.is_absolute():
        raise PathAccessError("絶対パスは指定できません")
    parts = [p for p in candidate.parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathAccessError("上位ディレクトリへの参照は許可されていません")
    return PurePosixPath(*parts) if parts else PurePosixPath()


def resolve_within_root(root: Root, rel_path: str, *, follow_symlinks: bool = False) -> Path:
    """ルート配下の実パスを返す。ルート外に出る場合は :class:`PathAccessError`。"""
    relative = normalise_relative(rel_path)
    base = root.real_path
    try:
        base_real = base.resolve(strict=True)
    except OSError as exc:
        raise PathAccessError(f"ルートフォルダを解決できません: {base}", status_code=404) from exc

    target = base_real / relative
    resolved = target.resolve() if follow_symlinks else Path(os.path.normpath(target))
    if not _is_within(resolved, base_real):
        raise PathAccessError("ルートフォルダの外は参照できません")
    if not follow_symlinks and target.is_symlink():
        # シンボリックリンク自体は辿らず、実体がルート内にある場合だけ許可する。
        linked = target.resolve()
        if not _is_within(linked, base_real):
            raise PathAccessError("ルート外へのシンボリックリンクは参照できません")
        resolved = linked
    return resolved


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return path == base
    return True


def relative_to_root(root: Root, path: Path) -> str:
    """ルートからの相対パスを POSIX 形式の文字列で返す。"""
    return path.relative_to(root.real_path).as_posix()
