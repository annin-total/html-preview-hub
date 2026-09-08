r"""ファイルシステムのスキャンとタイトル抽出。

- ルート配下を再帰的に走査し、対象拡張子のファイルをフォルダ単位でまとめる。
- タイトル抽出は先頭数十 KB だけを読み、(mtime, size) をキーにキャッシュする。
- HTML は `<title>` / `<h1>`、LaTeX は `\title` / `\chapter` / `\section` を見る。
"""

from __future__ import annotations

import fnmatch
import html as html_module
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, Root

_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(rb"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE)
_TAG_RE = re.compile(rb"<[^>]+>")
_WS_RE = re.compile(r"\s+")

#: LaTeX として扱う拡張子。
TEX_EXTENSIONS = frozenset({".tex", ".latex", ".ltx"})
#: HTML として扱う拡張子。
HTML_EXTENSIONS = frozenset({".html", ".htm", ".xhtml", ".xht"})

_TEX_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_TEX_TITLE_COMMANDS = ("title", "chapter", "section", "subsection")
_TEX_MACRO_RE = re.compile(r"\\[a-zA-Z@]+\s*(\[[^\]]*\])?")
_TEX_BRACES_RE = re.compile(r"[{}$]")


def kind_of(name: str) -> str:
    """ファイル名から種別（html / tex / other）を判定する。"""
    suffix = Path(name).suffix.lower()
    if suffix in TEX_EXTENSIONS:
        return "tex"
    if suffix in HTML_EXTENSIONS:
        return "html"
    return "other"


@dataclass(frozen=True)
class FileEntry:
    """スキャンで見つかった 1 ファイル。"""

    id: str
    root_id: str
    rel_path: str
    dir: str
    name: str
    title: str
    kind: str
    size: int
    created_at: float
    updated_at: float

    def to_json(self) -> dict[str, object]:
        """API レスポンス用の辞書へ変換する。"""
        return {
            "id": self.id,
            "rootId": self.root_id,
            "relPath": self.rel_path,
            "dir": self.dir,
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "size": self.size,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class FolderEntry:
    """ファイルを 1 つ以上含むフォルダ。"""

    id: str
    root_id: str
    root_name: str
    rel_path: str
    name: str
    depth: int
    file_ids: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_json(self) -> dict[str, object]:
        """API レスポンス用の辞書へ変換する。"""
        return {
            "id": self.id,
            "rootId": self.root_id,
            "rootName": self.root_name,
            "relPath": self.rel_path,
            "name": self.name,
            "depth": self.depth,
            "fileIds": self.file_ids,
            "fileCount": len(self.file_ids),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class ScanResult:
    """1 回のスキャン結果。"""

    files: list[FileEntry]
    folders: list[FolderEntry]
    errors: list[dict[str, str]]
    truncated: bool
    duration_ms: float
    scanned_at: float


class TitleCache:
    """(path, mtime, size) をキーにタイトルを保持する軽量キャッシュ。"""

    def __init__(self) -> None:
        """空のキャッシュを作る。"""
        self._entries: dict[str, tuple[float, int, str]] = {}

    def get(self, path: str, mtime: float, size: int) -> str | None:
        """変更されていなければキャッシュ済みタイトルを返す。"""
        cached = self._entries.get(path)
        if cached and cached[0] == mtime and cached[1] == size:
            return cached[2]
        return None

    def set(self, path: str, mtime: float, size: int, title: str) -> None:
        """タイトルをキャッシュする。"""
        self._entries[path] = (mtime, size, title)

    def prune(self, live_paths: set[str]) -> None:
        """存在しなくなったパスのエントリを捨てる。"""
        for path in list(self._entries):
            if path not in live_paths:
                del self._entries[path]

    def __len__(self) -> int:  # pragma: no cover - 診断用
        """キャッシュ件数。"""
        return len(self._entries)


def make_file_id(root_id: str, rel_path: str) -> str:
    """ファイル ID（`ルートID:相対パス`）を組み立てる。"""
    return f"{root_id}:{rel_path}"


def make_folder_id(root_id: str, rel_dir: str) -> str:
    """フォルダ ID（`ルートID:相対ディレクトリ`）を組み立てる。"""
    return f"{root_id}:{rel_dir}"


def extract_title(path: Path, *, limit: int, fallback: str) -> str:
    """ファイルの先頭から表示用タイトルを抽出する。失敗してもフォールバックを返す。"""
    try:
        with path.open("rb") as fh:
            head = fh.read(limit)
    except OSError:
        return fallback
    if not head:
        return fallback
    if kind_of(path.name) == "tex":
        return extract_tex_title(head.decode("utf-8", errors="replace")) or fallback
    encoding = _detect_encoding(head)
    for pattern in (_TITLE_RE, _H1_RE):
        match = pattern.search(head)
        if not match:
            continue
        text = _clean_text(match.group(1), encoding)
        if text:
            return text
    return fallback


def extract_tex_title(source: str) -> str:
    r"""LaTeX ソースから `\\title` → `\\chapter` → `\\section` の順にタイトルを探す。"""
    body = _TEX_COMMENT_RE.sub("", source)
    for command in _TEX_TITLE_COMMANDS:
        for match in re.finditer(rf"\\{command}\s*(?:\[[^\]]*\])?\s*\*?\s*{{", body):
            argument = _balanced_argument(body, match.end() - 1)
            text = _clean_tex_text(argument)
            if text:
                return text
    # タイトル系のコマンドが無い場合、先頭のコメント行を見出しとして使う。
    for line in source.splitlines()[:5]:
        stripped = line.strip()
        if stripped.startswith("%") and not stripped.startswith("% !"):
            text = _clean_tex_text(stripped.lstrip("%"))
            if text:
                return text
    return ""


def _balanced_argument(text: str, open_index: int) -> str:
    """`{` の位置から対応する `}` までを取り出す（入れ子に対応）。"""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{" and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif char == "}" and text[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    return text[open_index + 1 :]


def _clean_tex_text(raw: str) -> str:
    """LaTeX の断片から表示用の文字列を作る。"""
    text = raw.replace("\\\\", " ").replace("~", " ")
    text = _TEX_MACRO_RE.sub(" ", text)
    text = _TEX_BRACES_RE.sub("", text)
    text = text.replace("\\", "")  # `\&` などのエスケープを解く
    return _WS_RE.sub(" ", text).strip()


def _detect_encoding(head: bytes) -> str:
    match = _META_CHARSET_RE.search(head)
    if match:
        try:
            candidate = match.group(1).decode("ascii").lower()
            "".encode(candidate)  # 例外で未知のコーデックを弾く
            return candidate
        except (LookupError, UnicodeDecodeError):
            pass
    return "utf-8"


def _clean_text(raw: bytes, encoding: str) -> str:
    text = _TAG_RE.sub(b" ", raw).decode(encoding, errors="replace")
    text = html_module.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def scan(config: Config, cache: TitleCache | None = None) -> ScanResult:
    """設定されたすべてのルートをスキャンする（ブロッキング IO）。"""
    started = time.perf_counter()
    cache = cache if cache is not None else TitleCache()
    files: list[FileEntry] = []
    folders: dict[str, FolderEntry] = {}
    errors: list[dict[str, str]] = []
    live_paths: set[str] = set()
    extensions = tuple(config.include_extensions)
    truncated = False

    for root in config.roots:
        if not root.exists():
            errors.append({"rootId": root.id, "path": root.path, "message": "フォルダが見つかりません"})
            continue
        for entry in _walk_root(root, config, errors):
            if len(files) >= config.max_files:
                truncated = True
                break
            path, rel_path, stat = entry
            if not rel_path.lower().endswith(extensions):
                continue
            live_paths.add(str(path))
            fallback = Path(rel_path).stem
            title = cache.get(str(path), stat.st_mtime, stat.st_size)
            if title is None:
                title = extract_title(path, limit=config.title_scan_bytes, fallback=fallback)
                cache.set(str(path), stat.st_mtime, stat.st_size, title)
            rel_dir = str(Path(rel_path).parent.as_posix())
            rel_dir = "" if rel_dir == "." else rel_dir
            file_entry = FileEntry(
                id=make_file_id(root.id, rel_path),
                root_id=root.id,
                rel_path=rel_path,
                dir=rel_dir,
                name=Path(rel_path).name,
                title=title or fallback,
                kind=kind_of(rel_path),
                size=stat.st_size,
                created_at=_created_at(stat),
                updated_at=stat.st_mtime,
            )
            files.append(file_entry)
            folder = folders.get(make_folder_id(root.id, rel_dir))
            if folder is None:
                folder = FolderEntry(
                    id=make_folder_id(root.id, rel_dir),
                    root_id=root.id,
                    root_name=root.name,
                    rel_path=rel_dir,
                    name=Path(rel_dir).name if rel_dir else root.name,
                    depth=len(Path(rel_dir).parts) if rel_dir else 0,
                    created_at=file_entry.created_at,
                    updated_at=file_entry.updated_at,
                )
                folders[folder.id] = folder
            folder.file_ids.append(file_entry.id)
            folder.created_at = min(folder.created_at, file_entry.created_at)
            folder.updated_at = max(folder.updated_at, file_entry.updated_at)
        if truncated:
            break

    cache.prune(live_paths)
    for folder in folders.values():
        folder.file_ids.sort(key=lambda fid: fid.lower())
    return ScanResult(
        files=files,
        folders=list(folders.values()),
        errors=errors,
        truncated=truncated,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        scanned_at=time.time(),
    )


def _walk_root(
    root: Root, config: Config, errors: list[dict[str, str]]
) -> Iterable[tuple[Path, str, os.stat_result]]:
    """ルート配下を幅優先で走査し (実パス, 相対パス, stat) を返す。"""
    base = root.real_path
    ignore_dirs = set(config.ignore_dirs)
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as exc:
            errors.append({"rootId": root.id, "path": str(current), "message": str(exc)})
            continue
        for entry in entries:
            name = entry.name
            if name.startswith(".") and name not in {".", ".."}:
                continue
            path = Path(entry.path)
            try:
                rel_path = path.relative_to(base).as_posix()
            except ValueError:  # pragma: no cover - scandir の結果なので通常起きない
                continue
            if _matches_ignore(rel_path, config.ignore_globs):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=config.follow_symlinks)
            except OSError:
                continue
            if is_dir:
                if name in ignore_dirs or depth + 1 > config.max_depth:
                    continue
                stack.append((path, depth + 1))
                continue
            try:
                if not entry.is_file(follow_symlinks=config.follow_symlinks):
                    continue
                stat = entry.stat(follow_symlinks=config.follow_symlinks)
            except OSError as exc:
                errors.append({"rootId": root.id, "path": str(path), "message": str(exc)})
                continue
            yield path, rel_path, stat


def _matches_ignore(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def _created_at(stat: os.stat_result) -> float:
    """作成日時。プラットフォームで取得できない場合は最も近い値にフォールバック。"""
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime:
        return float(birthtime)
    return float(min(stat.st_ctime, stat.st_mtime))
