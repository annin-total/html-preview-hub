"""設定の読み込み・保存。

設定は JSON ファイルに永続化し、CLI 引数 / 環境変数 / UI から更新できる。
どの値もコード側にハードコードせず、既定値は :data:`DEFAULTS` に集約する。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

APP_NAME = "html-preview-hub"
ENV_CONFIG = "HPH_CONFIG"
ENV_ROOTS = "HPH_ROOTS"
ENV_STATE_DIR = "HPH_STATE_DIR"

#: 設定ファイルが存在しない / キーが欠けている場合に使う既定値。
DEFAULTS: dict[str, Any] = {
    "roots": [],
    "include_extensions": [".html", ".htm", ".xhtml", ".tex"],
    "ignore_dirs": [
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".next",
        ".nuxt",
        ".cache",
        "dist",
        "build",
        "target",
        ".mypy_cache",
        ".pytest_cache",
    ],
    "ignore_globs": [],
    "max_depth": 16,
    "max_files": 50000,
    "follow_symlinks": False,
    "title_scan_bytes": 65536,
    "watch_interval_seconds": 4.0,
    "host": "127.0.0.1",
    "port": 8765,
    "open_browser": True,
    # --- LaTeX プレビュー ---
    "tex_enabled": True,
    "tex_engine": "auto",
    "tex_use_latexmk": True,
    "tex_use_sibling_pdf": True,
    "tex_max_passes": 2,
    "tex_timeout_seconds": 90.0,
    "tex_cache_limit": 200,
    "tex_cache_dir": "",
}


def default_config_path() -> Path:
    """設定ファイルの既定パス（環境変数 > カレント > XDG 設定ディレクトリ）。"""
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env).expanduser()
    local = Path.cwd() / "config.json"
    if local.exists():
        return local
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / APP_NAME / "config.json"


def default_state_dir() -> Path:
    """お気に入り等のユーザー状態を置くディレクトリ。"""
    env = os.environ.get(ENV_STATE_DIR)
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / APP_NAME


def root_id_for(path: Path) -> str:
    """ルートパスから安定した ID を生成する（URL に埋め込むため短い hex）。"""
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return digest[:10]


@dataclass(frozen=True)
class Root:
    """スキャン対象のルートフォルダ。"""

    id: str
    name: str
    path: str

    @classmethod
    def create(cls, path: str | os.PathLike[str], name: str | None = None) -> Root:
        """パス（と任意の表示名）から Root を作る。ID はパスから決まる。"""
        resolved = Path(path).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:  # pragma: no cover - 解決不能でも設定自体は保持する
            resolved = resolved.absolute()
        label = (name or "").strip() or resolved.name or str(resolved)
        return cls(id=root_id_for(resolved), name=label, path=str(resolved))

    @property
    def real_path(self) -> Path:
        """設定されたパスを Path として返す。"""
        return Path(self.path)

    def exists(self) -> bool:
        """ルートが実在するディレクトリかどうか。"""
        return self.real_path.is_dir()


@dataclass
class Config:
    """アプリ全体の設定。"""

    roots: list[Root] = field(default_factory=list)
    include_extensions: list[str] = field(default_factory=lambda: list(DEFAULTS["include_extensions"]))
    ignore_dirs: list[str] = field(default_factory=lambda: list(DEFAULTS["ignore_dirs"]))
    ignore_globs: list[str] = field(default_factory=lambda: list(DEFAULTS["ignore_globs"]))
    max_depth: int = DEFAULTS["max_depth"]
    max_files: int = DEFAULTS["max_files"]
    follow_symlinks: bool = DEFAULTS["follow_symlinks"]
    title_scan_bytes: int = DEFAULTS["title_scan_bytes"]
    watch_interval_seconds: float = DEFAULTS["watch_interval_seconds"]
    host: str = DEFAULTS["host"]
    port: int = DEFAULTS["port"]
    open_browser: bool = DEFAULTS["open_browser"]
    tex_enabled: bool = DEFAULTS["tex_enabled"]
    tex_engine: str = DEFAULTS["tex_engine"]
    tex_use_latexmk: bool = DEFAULTS["tex_use_latexmk"]
    tex_use_sibling_pdf: bool = DEFAULTS["tex_use_sibling_pdf"]
    tex_max_passes: int = DEFAULTS["tex_max_passes"]
    tex_timeout_seconds: float = DEFAULTS["tex_timeout_seconds"]
    tex_cache_limit: int = DEFAULTS["tex_cache_limit"]
    tex_cache_dir: str = DEFAULTS["tex_cache_dir"]
    path: Path = field(default_factory=default_config_path)

    # ------------------------------------------------------------------
    # 読み書き
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """設定ファイル（無ければ既定値）と環境変数から Config を組み立てる。"""
        config_path = Path(path).expanduser() if path else default_config_path()
        raw: dict[str, Any] = {}
        if config_path.is_file():
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8")) or {}
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigError(f"設定ファイルを読み込めません: {config_path} ({exc})") from exc
            if not isinstance(raw, dict):
                raise ConfigError(f"設定ファイルの形式が不正です（オブジェクトが必要）: {config_path}")
        config = cls.from_dict(raw)
        config.path = config_path
        env_roots = os.environ.get(ENV_ROOTS, "").strip()
        if env_roots:
            for item in env_roots.split(os.pathsep):
                if item.strip():
                    config.add_root(item.strip())
        return config

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        """辞書から Config を作る。未知のキーは無視し、欠けたキーは既定値で補う。"""
        merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
        roots: list[Root] = []
        for entry in merged.get("roots") or []:
            if isinstance(entry, str):
                roots.append(Root.create(entry))
            elif isinstance(entry, dict) and entry.get("path"):
                roots.append(Root.create(entry["path"], entry.get("name")))
        config = cls(
            roots=_dedupe_roots(roots),
            include_extensions=_normalise_extensions(merged["include_extensions"]),
            ignore_dirs=[str(x) for x in merged["ignore_dirs"]],
            ignore_globs=[str(x) for x in merged["ignore_globs"]],
            max_depth=max(1, int(merged["max_depth"])),
            max_files=max(1, int(merged["max_files"])),
            follow_symlinks=bool(merged["follow_symlinks"]),
            title_scan_bytes=max(1024, int(merged["title_scan_bytes"])),
            watch_interval_seconds=max(0.0, float(merged["watch_interval_seconds"])),
            host=str(merged["host"]),
            port=int(merged["port"]),
            open_browser=bool(merged["open_browser"]),
            tex_enabled=bool(merged["tex_enabled"]),
            tex_engine=str(merged["tex_engine"]).strip() or "auto",
            tex_use_latexmk=bool(merged["tex_use_latexmk"]),
            tex_use_sibling_pdf=bool(merged["tex_use_sibling_pdf"]),
            tex_max_passes=max(1, int(merged["tex_max_passes"])),
            tex_timeout_seconds=max(5.0, float(merged["tex_timeout_seconds"])),
            tex_cache_limit=max(1, int(merged["tex_cache_limit"])),
            tex_cache_dir=str(merged["tex_cache_dir"]) or str(default_state_dir() / "tex-cache"),
        )
        return config

    def to_dict(self) -> dict[str, Any]:
        """設定ファイルに書き出せる辞書へ変換する。"""
        data = {key: getattr(self, key) for key in DEFAULTS if key != "roots"}
        data["roots"] = [asdict(root) for root in self.roots]
        return data

    def save(self) -> Path:
        """設定を JSON として原子的に保存し、保存先を返す。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    # ------------------------------------------------------------------
    # ルート操作
    # ------------------------------------------------------------------
    def add_root(self, path: str | os.PathLike[str], name: str | None = None) -> Root:
        """ルートを追加する。存在しない場合は ConfigError。既存なら既存を返す。"""
        root = Root.create(path, name)
        if not root.exists():
            raise ConfigError(f"フォルダが見つかりません: {root.path}")
        for existing in self.roots:
            if existing.id == root.id:
                return existing
        self.roots.append(root)
        return root

    def remove_root(self, root_id: str) -> bool:
        """ルートを削除する。削除できたら True。"""
        before = len(self.roots)
        self.roots = [r for r in self.roots if r.id != root_id]
        return len(self.roots) != before

    def rename_root(self, root_id: str, name: str) -> Root | None:
        """ルートの表示名を変更する。対象が無ければ None。"""
        for i, root in enumerate(self.roots):
            if root.id == root_id:
                updated = replace(root, name=name.strip() or root.name)
                self.roots[i] = updated
                return updated
        return None

    def root(self, root_id: str) -> Root | None:
        """ID からルートを引く。"""
        return next((r for r in self.roots if r.id == root_id), None)


class ConfigError(RuntimeError):
    """設定の不備を表す例外。"""


def _normalise_extensions(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        ext = str(value).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in out:
            out.append(ext)
    return out or list(DEFAULTS["include_extensions"])


def _dedupe_roots(roots: list[Root]) -> list[Root]:
    seen: set[str] = set()
    out: list[Root] = []
    for root in roots:
        if root.id in seen:
            continue
        seen.add(root.id)
        out.append(root)
    return out
