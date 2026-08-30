"""CLI エントリポイント: `python -m hph`。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .config import Config, ConfigError
from .server import create_app, open_browser_later


def build_parser() -> argparse.ArgumentParser:
    """CLI 引数パーサを作る。"""
    parser = argparse.ArgumentParser(
        prog="python -m hph",
        description="ローカルの HTML ファイルを一覧・検索・プレビューするローカルサーバー",
    )
    parser.add_argument("roots", nargs="*", help="スキャン対象のフォルダ（省略時は設定ファイルの値）")
    parser.add_argument("-c", "--config", type=Path, default=None, help="設定ファイルのパス")
    parser.add_argument("--host", default=None, help="バインドするホスト（既定: 設定ファイルの値）")
    parser.add_argument("--port", type=int, default=None, help="ポート番号")
    parser.add_argument("--no-browser", action="store_true", help="起動時にブラウザを開かない")
    parser.add_argument("--save", action="store_true", help="指定したフォルダを設定ファイルへ保存する")
    parser.add_argument("--reload", action="store_true", help="開発用オートリロード")
    parser.add_argument("--log-level", default="info", help="uvicorn のログレベル")
    parser.add_argument("--version", action="version", version=f"html-preview-hub {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    """アプリを起動する。異常終了時は非 0 を返す。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    try:
        config = Config.load(args.config)
        for raw_root in args.roots:
            config.add_root(raw_root)
        if args.save:
            config.save()
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.no_browser:
        config.open_browser = False

    if not config.roots:
        print(
            "対象フォルダが未設定です。引数で指定するか、起動後に画面右上の設定から追加してください。\n"
            f"  例: python -m hph ~/Documents/html --save\n"
            f"  設定ファイル: {config.path}",
            file=sys.stderr,
        )

    url = f"http://{_display_host(config.host)}:{config.port}/"
    print(f"html-preview-hub {__version__} → {url}")
    for root in config.roots:
        state = "" if root.exists() else "  (見つかりません)"
        print(f"  - {root.name}: {root.path}{state}")
    if config.open_browser:
        open_browser_later(url)

    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level=args.log_level, access_log=False)
    return 0


def _display_host(host: str) -> str:
    return "localhost" if host in {"0.0.0.0", "::", ""} else host


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
