"""同じホスト・ポートで起動済みのインスタンスを検出し、二重起動を防ぐ。"""

from __future__ import annotations

import enum
import http.client
import json
import socket
import urllib.request

from .config import APP_NAME

HEALTH_PATH = "/api/health"
PROBE_TIMEOUT_SECONDS = 2.0
# ワイルドカードのアドレスへは接続できない環境（Windows）があるため、ループバックへ読み替える
_WILDCARD_TO_LOOPBACK = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}


class PortState(enum.Enum):
    """ポートの使用状況。"""

    FREE = "free"
    RUNNING = "running"
    OCCUPIED = "occupied"


def probe(host: str, port: int, timeout: float = PROBE_TIMEOUT_SECONDS) -> PortState:
    """host:port が空いているか、html-preview-hub か、別のアプリが使っているかを調べる。"""
    target = _WILDCARD_TO_LOOPBACK.get(host, host)
    try:
        with socket.create_connection((target, port), timeout=timeout):
            pass
    except OSError:
        return PortState.FREE

    url_host = f"[{target}]" if ":" in target else target
    # localhost 宛てでも HTTP_PROXY を経由させない
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{url_host}:{port}{HEALTH_PATH}", timeout=timeout) as response:
            body = json.loads(response.read())
    except (OSError, ValueError, http.client.HTTPException):
        return PortState.OCCUPIED
    if isinstance(body, dict) and body.get("app") == APP_NAME:
        return PortState.RUNNING
    return PortState.OCCUPIED
