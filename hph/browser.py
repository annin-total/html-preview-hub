"""起動時に既定のブラウザでアプリの画面を開く。"""

from __future__ import annotations

import logging
import threading
import time
import webbrowser

from .instance import PortState, probe

logger = logging.getLogger(__name__)

BROWSER_WAIT_SECONDS = 120.0
BROWSER_POLL_SECONDS = 0.3


def open_browser(url: str) -> None:
    """既定のブラウザで開く。開けなくても起動は続ける。"""
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover - 環境依存
        logger.debug("ブラウザを自動起動できませんでした", exc_info=True)


def open_browser_when_ready(url: str, host: str, port: int) -> threading.Thread:
    """サーバーが応答し始めてからブラウザを開く（初回スキャン中に開くと接続エラーの画面になるため）。"""

    def _wait_and_open() -> None:
        deadline = time.monotonic() + BROWSER_WAIT_SECONDS
        while probe(host, port) is not PortState.RUNNING:
            if time.monotonic() > deadline:
                logger.warning("サーバーが応答しないため、ブラウザを開きませんでした")
                return
            time.sleep(BROWSER_POLL_SECONDS)
        open_browser(url)

    thread = threading.Thread(target=_wait_and_open, daemon=True)
    thread.start()
    return thread
