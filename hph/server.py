"""FastAPI アプリケーション本体（API ルーティングとファイル配信）。"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Config, ConfigError, default_state_dir
from .index import IndexService
from .paths import PathAccessError, resolve_within_root
from .scanner import kind_of
from .store import UserStore
from .tex import available_engines, has_dvipdfmx, has_latexmk
from .tex import cached_pdf as cached_tex_pdf
from .texjobs import TexJob, TexJobRegistry

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
RAW_PREFIX = "/raw"
WATCH_TIMEOUT_SECONDS = 25.0
SOURCE_MAX_BYTES = 2 * 1024 * 1024
DIRECTORY_INDEX_NAMES = ("index.html", "index.htm")
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE)
_RAW_REFERER_RE = re.compile(rf"{RAW_PREFIX}/([0-9a-f]+)/")

mimetypes.init()
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/plain", ".tex")
mimetypes.add_type("application/pdf", ".pdf")


def create_app(config: Config, *, store: UserStore | None = None) -> FastAPI:
    """設定を受け取ってアプリを構築する（テストからも利用する）。"""
    user_store = store or UserStore(default_state_dir())
    index = IndexService(config, user_store)

    # LaTeX のコンパイルはバックグラウンドで走らせ、ファイルを切り替えても中断しない。
    tex_jobs = TexJobRegistry()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await index.start()
        try:
            yield
        finally:
            await tex_jobs.shutdown()
            await index.stop()

    app = FastAPI(title="html-preview-hub", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.index = index
    app.state.store = user_store
    app.state.tex_jobs = tex_jobs

    # ------------------------------------------------------------------
    # インデックス
    # ------------------------------------------------------------------
    @app.get("/api/index")
    async def get_index() -> JSONResponse:
        return JSONResponse(index.to_json())

    @app.get("/api/index/watch")
    async def watch_index(revision: int = Query(0, ge=0)) -> JSONResponse:
        """ロングポーリング。リビジョンが進むか、タイムアウトすると返る。"""
        new_revision = await index.wait_for_change(revision, WATCH_TIMEOUT_SECONDS)
        return JSONResponse({"revision": index.snapshot.revision, "changed": new_revision is not None})

    @app.post("/api/rescan")
    async def rescan() -> JSONResponse:
        await index.rescan()
        return JSONResponse(index.to_json())

    # ------------------------------------------------------------------
    # 設定 / ルートフォルダ
    # ------------------------------------------------------------------
    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        return JSONResponse({"config": config.to_dict(), "configPath": str(config.path)})

    @app.put("/api/config")
    async def update_config(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        updatable = {
            "include_extensions": list,
            "ignore_dirs": list,
            "ignore_globs": list,
            "max_depth": int,
            "max_files": int,
            "follow_symlinks": bool,
            "watch_interval_seconds": float,
            "open_browser": bool,
            "tex_enabled": bool,
            "tex_engine": str,
            "tex_use_latexmk": bool,
            "tex_use_sibling_pdf": bool,
            "tex_max_passes": int,
            "tex_timeout_seconds": float,
        }
        try:
            for key, caster in updatable.items():
                if key in payload:
                    setattr(config, key, caster(payload[key]))
            config.save()
        except (TypeError, ValueError, OSError) as exc:
            return _error(f"設定を更新できません: {exc}", 400)
        await index.rescan(force=True)
        return JSONResponse({"config": config.to_dict(), "configPath": str(config.path)})

    @app.post("/api/roots")
    async def add_root(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            return _error("path は必須です", 400)
        try:
            root = config.add_root(raw_path, payload.get("name"))
            config.save()
        except (ConfigError, OSError) as exc:
            return _error(str(exc), 400)
        await index.rescan(force=True)
        return JSONResponse({"root": {"id": root.id, "name": root.name, "path": root.path}})

    @app.patch("/api/roots/{root_id}")
    async def rename_root(root_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        root = config.rename_root(root_id, str(payload.get("name", "")))
        if root is None:
            return _error("ルートが見つかりません", 404)
        config.save()
        await index.rescan(force=True)
        return JSONResponse({"root": {"id": root.id, "name": root.name, "path": root.path}})

    @app.delete("/api/roots/{root_id}")
    async def remove_root(root_id: str) -> JSONResponse:
        if not config.remove_root(root_id):
            return _error("ルートが見つかりません", 404)
        config.save()
        await index.rescan(force=True)
        return JSONResponse({"ok": True})

    @app.get("/api/browse")
    async def browse(path: str | None = Query(default=None)) -> JSONResponse:
        """ルート追加用の簡易ディレクトリブラウザ（サブディレクトリのみ返す）。"""
        target = Path(path).expanduser() if path else Path.home()
        try:
            target = target.resolve()
        except OSError as exc:
            return _error(f"パスを解決できません: {exc}", 400)
        if not target.is_dir():
            return _error(f"ディレクトリではありません: {target}", 400)
        try:
            children = sorted(
                (entry for entry in os.scandir(target) if _is_listable_dir(entry)),
                key=lambda e: e.name.lower(),
            )
        except OSError as exc:
            return _error(f"ディレクトリを読み取れません: {exc}", 403)
        return JSONResponse(
            {
                "path": str(target),
                "parent": str(target.parent) if target.parent != target else None,
                "home": str(Path.home()),
                "entries": [{"name": e.name, "path": e.path} for e in children],
            }
        )

    # ------------------------------------------------------------------
    # ユーザー状態
    # ------------------------------------------------------------------
    @app.post("/api/user/favorites")
    async def toggle_favorite(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        return _toggle(user_store, "favorites", payload.get("fileId"))

    @app.post("/api/user/hidden")
    async def toggle_hidden(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        return _toggle(user_store, "hiddenFolders", payload.get("folderId"))

    @app.post("/api/user/recents")
    async def touch_recent(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        file_id = str(payload.get("fileId", "")).strip()
        if not file_id:
            return _error("fileId は必須です", 400)
        return JSONResponse({"recents": user_store.touch_recent(file_id)})

    # ------------------------------------------------------------------
    # ファイル
    # ------------------------------------------------------------------
    @app.get("/api/tex/status")
    async def tex_status() -> JSONResponse:
        """LaTeX の実行環境（利用可能なエンジンなど）を返す。"""
        engines = await asyncio.to_thread(available_engines)
        return JSONResponse(
            {
                "enabled": config.tex_enabled,
                "engines": sorted(engines),
                "latexmk": has_latexmk(),
                "dvipdfmx": has_dvipdfmx(),
                "configuredEngine": config.tex_engine,
            }
        )

    @app.post("/api/tex/compile")
    async def tex_compile(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        """`.tex` のコンパイルを開始し、その時点の状態を返す（完了は待たない）。

        すぐ終わるもの（キャッシュ済みなど）は 1 往復で結果まで返し、時間がかかる
        ものは `status: "running"` を返す。続きは `/api/tex/job` で受け取る。
        """
        file_id = str(payload.get("fileId", ""))
        entry = index.file(file_id)
        if entry is None:
            return _error("ファイルが見つかりません", 404)
        if kind_of(entry.name) != "tex":
            return _error("LaTeX ファイルではありません", 400)
        root = config.root(entry.root_id)
        if root is None:
            return _error("ルートが見つかりません", 404)
        try:
            path = resolve_within_root(root, entry.rel_path, follow_symlinks=config.follow_symlinks)
        except PathAccessError as exc:
            return _error(exc.message, exc.status_code)

        job = tex_jobs.submit(file_id, path, config, force=bool(payload.get("force")))
        await tex_jobs.settle(job)
        return JSONResponse(_tex_job_body(file_id, job))

    @app.get("/api/tex/job")
    async def tex_job(fileId: str = Query(...)) -> JSONResponse:
        """バックグラウンドで走っているコンパイルの状態を返す。"""
        job = tex_jobs.get(fileId)
        if job is None:
            return _error("コンパイルの記録がありません。もう一度開いてください", 404)
        return JSONResponse(_tex_job_body(fileId, job))

    @app.get("/api/tex/pdf")
    async def tex_pdf(fileId: str = Query(...), v: str = Query(...)) -> Response:
        """コンパイル済み PDF を返す（プレビューの iframe から参照する）。"""
        entry = index.file(fileId)
        if entry is None:
            return _file_error("ファイルが見つかりません", 404)
        root = config.root(entry.root_id)
        if root is None:
            return _file_error("ルートが見つかりません", 404)
        try:
            path = resolve_within_root(root, entry.rel_path, follow_symlinks=config.follow_symlinks)
        except PathAccessError as exc:
            return _file_error(exc.message, exc.status_code)
        pdf = cached_tex_pdf(path, config, v)
        if pdf is None:
            return _file_error("PDF がまだ生成されていません。再コンパイルしてください", 404)
        return FileResponse(
            pdf,
            media_type="application/pdf",
            headers={"Cache-Control": "no-cache, must-revalidate", "Content-Disposition": "inline"},
        )

    @app.get("/api/source")
    async def get_source(fileId: str = Query(...)) -> JSONResponse:
        entry = index.file(fileId)
        if entry is None:
            return _error("ファイルが見つかりません", 404)
        root = config.root(entry.root_id)
        if root is None:
            return _error("ルートが見つかりません", 404)
        try:
            path = resolve_within_root(root, entry.rel_path, follow_symlinks=config.follow_symlinks)
            data = path.read_bytes()[:SOURCE_MAX_BYTES]
        except PathAccessError as exc:
            return _error(exc.message, exc.status_code)
        except OSError as exc:
            return _error(f"ファイルを読み取れません: {exc}", 500)
        return JSONResponse(
            {
                "fileId": fileId,
                "path": str(path),
                "truncated": path.stat().st_size > SOURCE_MAX_BYTES,
                "text": data.decode(_charset_of(data[:4096]), errors="replace"),
            }
        )

    @app.post("/api/open")
    async def open_externally(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        entry = index.file(str(payload.get("fileId", "")))
        if entry is None:
            return _error("ファイルが見つかりません", 404)
        root = config.root(entry.root_id)
        if root is None:
            return _error("ルートが見つかりません", 404)
        try:
            path = resolve_within_root(root, entry.rel_path, follow_symlinks=config.follow_symlinks)
            opened = webbrowser.open(path.as_uri())
        except PathAccessError as exc:
            return _error(exc.message, exc.status_code)
        except (OSError, webbrowser.Error) as exc:  # pragma: no cover - 環境依存
            return _error(f"ブラウザを開けません: {exc}", 500)
        return JSONResponse({"ok": bool(opened), "path": str(path)})

    @app.api_route(RAW_PREFIX + "/{root_id}/{rel_path:path}", methods=["GET", "HEAD"])
    async def serve_raw(root_id: str, rel_path: str) -> Response:
        """プレビュー本体と、それが参照する相対アセットを配信する。"""
        return _serve(config, root_id, rel_path)

    # ------------------------------------------------------------------
    # 静的アセットと SPA シェル
    # ------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index_page() -> Response:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def fallback(full_path: str, request: Request) -> Response:
        """プレビュー HTML がルート絶対パス（例 `/assets/app.css`）を参照した場合の救済。

        Referer から元のルートを特定し、そのルート基準で解決する。
        """
        referer = request.headers.get("referer", "")
        match = _RAW_REFERER_RE.search(referer)
        if match:
            return _serve(config, match.group(1), full_path)
        return _error("見つかりません", 404)

    return app


# ----------------------------------------------------------------------
# ヘルパー
# ----------------------------------------------------------------------
def _tex_job_body(file_id: str, job: TexJob) -> dict[str, Any]:
    """ジョブの状態を API レスポンス用の辞書へ変換し、成功時は PDF の URL を添える。"""
    body = job.to_json()
    if body.get("status") == "ok":
        fingerprint = str(body.get("fingerprint", ""))
        body["pdfUrl"] = (
            f"/api/tex/pdf?fileId={quote(file_id, safe='')}&v={quote(fingerprint, safe='')}"
        )
    return body


def _serve(config: Config, root_id: str, rel_path: str) -> Response:
    root = config.root(root_id)
    if root is None:
        return _file_error("指定されたルートフォルダは登録されていません", 404)
    try:
        path = resolve_within_root(root, rel_path, follow_symlinks=config.follow_symlinks)
    except PathAccessError as exc:
        return _file_error(exc.message, exc.status_code)
    if path.is_dir():
        for name in DIRECTORY_INDEX_NAMES:
            candidate = path / name
            if candidate.is_file():
                path = candidate
                break
        else:
            return _file_error(f"ディレクトリにはプレビューできるファイルがありません: {rel_path}", 404)
    if not path.is_file():
        return _file_error(f"ファイルが見つかりません: {rel_path}", 404)
    try:
        media_type = _media_type_for(path)
        headers = {
            "Cache-Control": "no-cache, must-revalidate",
            # サンドボックス iframe は opaque origin になるため、明示的に許可する。
            "Access-Control-Allow-Origin": "*",
            "X-Frame-Options": "SAMEORIGIN",
        }
        return FileResponse(path, media_type=media_type, headers=headers)
    except OSError as exc:
        return _file_error(f"ファイルを読み取れません: {exc}", 500)


def _media_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in {"application/json", "image/svg+xml"}:
        if guessed == "text/html":
            # 文書自身が charset を宣言していればブラウザの判定に委ねる。
            try:
                head = path.open("rb").read(4096)
            except OSError:
                head = b""
            if _META_CHARSET_RE.search(head):
                return "text/html"
            return "text/html; charset=utf-8"
        return f"{guessed}; charset=utf-8"
    return guessed


def _charset_of(head: bytes) -> str:
    match = _META_CHARSET_RE.search(head)
    if match:
        try:
            candidate = match.group(1).decode("ascii").lower()
            "".encode(candidate)
            return candidate
        except (LookupError, UnicodeDecodeError):
            pass
    return "utf-8"


def _is_listable_dir(entry: os.DirEntry[str]) -> bool:
    if entry.name.startswith("."):
        return False
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:  # pragma: no cover - 権限エラー等
        return False


def _toggle(store: UserStore, key: str, value: Any) -> JSONResponse:
    identifier = str(value or "").strip()
    if not identifier:
        return _error("ID は必須です", 400)
    added = store.toggle(key, identifier)
    return JSONResponse({"added": added, key: store.snapshot()[key]})


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _file_error(message: str, status_code: int) -> HTMLResponse:
    """iframe 内にそのまま表示できるエラーページ。"""
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>プレビューを表示できません</title>
<style>
  body {{ margin:0; display:grid; place-items:center; min-height:100vh;
         font-family: system-ui, -apple-system, "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif;
         background:#F6F4EF; color:#2B2A27; }}
  .box {{ max-width:min(520px, 84vw); padding:28px 32px; background:#fff;
          border:1px solid #E7E3DA; border-radius:14px; text-align:center; }}
  h1 {{ font-size:15px; margin:0 0 8px; letter-spacing:.02em; }}
  p  {{ font-size:13px; line-height:1.7; color:#6F6B62; margin:0; word-break:break-all; }}
</style></head>
<body><div class="box"><h1>プレビューを表示できません</h1><p>{safe}</p></div></body></html>"""
    return HTMLResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})


def open_browser_later(url: str, delay: float = 1.0) -> None:
    """起動直後にブラウザを開く（サーバー起動を妨げないよう別スレッドで）。"""
    import threading

    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - 環境依存
            logger.debug("ブラウザを自動起動できませんでした", exc_info=True)

    threading.Timer(delay, _open).start()
