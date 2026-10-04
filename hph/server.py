"""FastAPI アプリケーション本体（API ルーティングとファイル配信）。"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import APP_NAME, Config, ConfigError, default_state_dir
from .index import IndexService
from .instance import HEALTH_PATH
from .paths import PathAccessError, resolve_within_root
from .picker import pick_folder
from .rawfiles import file_error, serve_file
from .rules import parse_rules
from .scanner import FileEntry, detect_charset, kind_of
from .store import UserStore
from .tex import available_engines, has_dvipdfmx, has_latexmk
from .tex import cached_pdf as cached_tex_pdf
from .texjobs import TexJob, TexJobRegistry

STATIC_DIR = Path(__file__).parent / "static"
REVALIDATE = {"Cache-Control": "no-cache"}


class RevalidatedStaticFiles(StaticFiles):
    """配信のたびにブラウザへ再検証させ、更新後に古いフロントエンドが残らないようにする。"""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        """`Cache-Control: no-cache` を付けたファイル応答を返す。"""
        response = super().file_response(*args, **kwargs)
        response.headers.update(REVALIDATE)
        return response


RAW_PREFIX = "/raw"
# 停止時、uvicorn は処理中のリクエストを最大 SHUTDOWN_TIMEOUT_SECONDS 待ってから取り消す
# （取り消すとトレースバックが出る）。ロングポーリングはそれより短く保留し、待機中に自然に返るようにする。
WATCH_TIMEOUT_SECONDS = 4.0
SHUTDOWN_TIMEOUT_SECONDS = 5
SOURCE_MAX_BYTES = 2 * 1024 * 1024
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_RAW_REFERER_RE = re.compile(rf"{RAW_PREFIX}/([0-9a-f]+)/")


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

    def _resolve_entry(entry: FileEntry | None) -> Path:
        """インデックス上のファイルを実パスへ解決する。解決できなければ PathAccessError。"""
        if entry is None:
            raise PathAccessError("ファイルが見つかりません", 404)
        root = config.root(entry.root_id)
        if root is None:
            raise PathAccessError("ルートが見つかりません", 404)
        return resolve_within_root(root, entry.rel_path, follow_symlinks=config.follow_symlinks)

    pick_lock = asyncio.Lock()

    @app.post("/api/pick-folder")
    async def pick_folder_route(request: Request) -> JSONResponse:
        """OS のフォルダ選択画面を開く。画面は利用者の PC に出るため、同じ PC からの要求に限る。"""
        if not _is_loopback(request):
            return _error("この操作は、アプリを動かしている PC からだけ行えます", 403)
        if not _is_loopback_host(request):
            return _error("この操作は、localhost のアドレスからだけ行えます", 403)
        if not _is_same_origin(request):
            return _error("別のサイトからは、この操作を行えません", 403)
        if pick_lock.locked():
            return _error("フォルダの選択画面がすでに開いています", 409)
        async with pick_lock:
            result = await asyncio.to_thread(pick_folder)
        return JSONResponse(result.to_json())

    @app.get(HEALTH_PATH)
    async def health() -> JSONResponse:
        """起動済みのインスタンスを見分けるための応答。"""
        return JSONResponse({"app": APP_NAME, "version": __version__})

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
            "ignore_globs": list,
            "exclude": list,
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
            changes = {key: caster(payload[key]) for key, caster in updatable.items() if key in payload}
            # 設定ファイルの読み込みと同じ補正（下限・拡張子の正規化など）を通す
            normalized = Config.from_dict({**config.to_dict(), **changes})
            for key in changes:
                setattr(config, key, getattr(normalized, key))
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
        return JSONResponse({"root": root.to_dict()})

    @app.patch("/api/roots/{root_id}")
    async def update_root(root_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        try:
            exclude = parse_rules(payload["exclude"]) if "exclude" in payload else None
        except ValueError as exc:
            return _error(str(exc), 400)
        root = config.update_root(root_id, name=str(payload.get("name", "")), exclude=exclude)
        if root is None:
            return _error("ルートが見つかりません", 404)
        config.save()
        await index.rescan(force=True)
        return JSONResponse({"root": root.to_dict()})

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
        if entry is not None and kind_of(entry.name) != "tex":
            return _error("LaTeX ファイルではありません", 400)
        try:
            path = _resolve_entry(entry)
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
        try:
            path = _resolve_entry(index.file(fileId))
        except PathAccessError as exc:
            return file_error(exc.message, exc.status_code)
        pdf = cached_tex_pdf(path, config, v)
        if pdf is None:
            return file_error("PDF がまだ生成されていません。再コンパイルしてください", 404)
        return FileResponse(
            pdf,
            media_type="application/pdf",
            headers={"Cache-Control": "no-cache, must-revalidate", "Content-Disposition": "inline"},
        )

    @app.get("/api/source")
    async def get_source(fileId: str = Query(...)) -> JSONResponse:
        try:
            path = _resolve_entry(index.file(fileId))
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
                "text": data.decode(detect_charset(data[:4096]), errors="replace"),
            }
        )

    @app.post("/api/open")
    async def open_externally(payload: dict[str, Any] = Body(default_factory=dict)) -> JSONResponse:
        try:
            path = _resolve_entry(index.file(str(payload.get("fileId", ""))))
            opened = webbrowser.open(path.as_uri())
        except PathAccessError as exc:
            return _error(exc.message, exc.status_code)
        except (OSError, webbrowser.Error) as exc:  # pragma: no cover - 環境依存
            return _error(f"ブラウザを開けません: {exc}", 500)
        return JSONResponse({"ok": bool(opened), "path": str(path)})

    @app.api_route(RAW_PREFIX + "/{root_id}/{rel_path:path}", methods=["GET", "HEAD"])
    async def serve_raw(root_id: str, rel_path: str) -> Response:
        """プレビュー本体と、それが参照する相対アセットを配信する。"""
        return serve_file(config, root_id, rel_path)

    # ------------------------------------------------------------------
    # 静的アセットと SPA シェル
    # ------------------------------------------------------------------
    app.mount("/static", RevalidatedStaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index_page() -> Response:
        return FileResponse(
            STATIC_DIR / "index.html", media_type="text/html; charset=utf-8", headers=REVALIDATE
        )

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def fallback(full_path: str, request: Request) -> Response:
        """プレビュー HTML がルート絶対パス（例 `/assets/app.css`）を参照した場合の救済。

        Referer から元のルートを特定し、そのルート基準で解決する。
        """
        referer = request.headers.get("referer", "")
        match = _RAW_REFERER_RE.search(referer)
        if match:
            return serve_file(config, match.group(1), full_path)
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
        body["pdfUrl"] = f"/api/tex/pdf?fileId={quote(file_id, safe='')}&v={quote(fingerprint, safe='')}"
    return body


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


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback_host(request: Request) -> bool:
    """Host ヘッダがループバックの名前であること（DNS リバインディング対策）。"""
    host = request.headers.get("host")
    return host is not None and urlsplit(f"//{host}").hostname in LOOPBACK_HOSTS


def _is_same_origin(request: Request) -> bool:
    """Origin ヘッダがあれば、Host と一致するときだけ許す（他サイトからの単純リクエストを拒む）。"""
    origin = request.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == request.headers.get("host")


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)
