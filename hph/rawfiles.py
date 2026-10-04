"""`/raw` 配下のファイル配信（プレビュー本体と、それが参照するアセット）。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, Response

from .config import Config
from .paths import PathAccessError, resolve_within_root
from .scanner import META_CHARSET_RE

DIRECTORY_INDEX_NAMES = ("index.html", "index.htm")

mimetypes.init()
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/plain", ".tex")
mimetypes.add_type("application/pdf", ".pdf")


def serve_file(config: Config, root_id: str, rel_path: str) -> Response:
    """ルート配下のファイルを配信する。ディレクトリなら index.html を探す。"""
    root = config.root(root_id)
    if root is None:
        return file_error("指定されたルートフォルダは登録されていません", 404)
    try:
        path = resolve_within_root(root, rel_path, follow_symlinks=config.follow_symlinks)
    except PathAccessError as exc:
        return file_error(exc.message, exc.status_code)
    if path.is_dir():
        for name in DIRECTORY_INDEX_NAMES:
            candidate = path / name
            if candidate.is_file():
                path = candidate
                break
        else:
            return file_error(f"ディレクトリにはプレビューできるファイルがありません: {rel_path}", 404)
    if not path.is_file():
        return file_error(f"ファイルが見つかりません: {rel_path}", 404)
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
        return file_error(f"ファイルを読み取れません: {exc}", 500)


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
            if META_CHARSET_RE.search(head):
                return "text/html"
            return "text/html; charset=utf-8"
        return f"{guessed}; charset=utf-8"
    return guessed


def file_error(message: str, status_code: int) -> HTMLResponse:
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
