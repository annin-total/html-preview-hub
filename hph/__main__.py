"""CLI エントリポイント: `python -m hph`。"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import time
from pathlib import Path

import uvicorn

from . import __version__
from .browser import open_browser, open_browser_when_ready
from .config import Config, ConfigError
from .instance import PortState, probe
from .server import SHUTDOWN_TIMEOUT_SECONDS, create_app

EXIT_CONFIG_ERROR = 2
EXIT_ALREADY_RUNNING = 3
STOP_GUIDE = (
    "停止するには、このウインドウで Ctrl+C を 1 回だけ押してください。\n"
    "停止処理には少し時間がかかります（通常は数秒）。"
    "Ctrl+C を 2 回押すと強制終了になるため、押さずにそのままお待ちください。"
)


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
    parser.add_argument("--log-level", default="info", help="uvicorn のログレベル")
    parser.add_argument(
        "--pause-on-exit",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="終了前に指定秒数待つ（エラー時は Enter を待つ）。ショートカットからの起動用",
    )
    parser.add_argument("--version", action="version", version=f"html-preview-hub {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    """アプリを起動する。異常終了時は非 0 を返す。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
    try:
        code = _run(args)
    except SystemExit as exc:
        # uvicorn は起動に失敗すると sys.exit する。終了コードは版で異なり、
        # 3（起動済み）と衝突しうるため 1 に揃える
        code = 0 if exc.code in (0, None) else 1
    if args.pause_on_exit > 0:
        _pause_before_exit(code, args.pause_on_exit)
    return code


def _run(args: argparse.Namespace) -> int:
    try:
        config = Config.load(args.config)
        for raw_root in args.roots:
            config.add_root(raw_root)
        if args.save:
            config.save()
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.no_browser:
        config.open_browser = False

    url = f"http://{_display_host(config.host)}:{config.port}/"
    state = probe(config.host, config.port)
    if state is PortState.RUNNING:
        print(f"html-preview-hub はすでに起動しています → {url}")
        if config.open_browser:
            print("起動中の画面をブラウザで開きます。")
            open_browser(url)
        return EXIT_ALREADY_RUNNING
    if state is PortState.OCCUPIED:
        print(
            f"エラー: ポート {config.port} は別のアプリが使用しています。"
            "--port で別のポートを指定してください。",
            file=sys.stderr,
        )
        return 1

    if not config.roots:
        print(
            "対象フォルダが未設定です。引数で指定するか、起動後に画面右上の設定から追加してください。\n"
            f"  例: python -m hph ~/Documents/html --save\n"
            f"  設定ファイル: {config.path}",
            file=sys.stderr,
        )

    print(f"html-preview-hub {__version__} → {url}")
    for root in config.roots:
        missing = "" if root.exists() else "  (見つかりません)"
        print(f"  - {root.name}: {root.path}{missing}")
    print(STOP_GUIDE)
    if config.open_browser:
        open_browser_when_ready(url, config.host, config.port)

    app = create_app(config)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=args.log_level,
        access_log=False,
        timeout_graceful_shutdown=SHUTDOWN_TIMEOUT_SECONDS,
    )
    print("停止しました。")
    return 0


def _pause_before_exit(code: int, seconds: float) -> None:
    with contextlib.suppress(KeyboardInterrupt, EOFError):
        if code in (0, EXIT_ALREADY_RUNNING):
            print(f"{seconds:g} 秒後にこのウインドウを閉じます。")
            time.sleep(seconds)
        else:
            input("エラーで終了しました。Enter キーを押すとこのウインドウを閉じます。")


def _display_host(host: str) -> str:
    return "localhost" if host in {"0.0.0.0", "::", ""} else host


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
