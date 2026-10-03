"""二重起動の検出と、ショートカット起動向けの終了処理の検証。"""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hph.__main__ as cli
import hph.server as server
from hph.config import APP_NAME
from hph.instance import HEALTH_PATH, PortState, probe


def _serve(server: socketserver.BaseServer) -> Iterator[int]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _json_server(body: object) -> Callable[[], Iterator[int]]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = json.dumps(body).encode()
            self.send_response(200 if self.path == HEALTH_PATH else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            pass

    return lambda: _serve(HTTPServer(("127.0.0.1", 0), Handler))


class _GarbageHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.sendall(b"not http at all\r\n\r\n")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_probe_free_port() -> None:
    assert probe("127.0.0.1", _free_port()) is PortState.FREE


def test_probe_detects_running_instance() -> None:
    for port in _json_server({"app": APP_NAME, "version": "x"})():
        assert probe("127.0.0.1", port) is PortState.RUNNING
        assert probe("0.0.0.0", port) is PortState.RUNNING


@pytest.mark.parametrize("body", [{"app": "other"}, ["not", "a", "dict"]])
def test_probe_other_http_app_is_occupied(body: object) -> None:
    for port in _json_server(body)():
        assert probe("127.0.0.1", port) is PortState.OCCUPIED


def test_probe_non_http_service_is_occupied() -> None:
    for port in _serve(socketserver.TCPServer(("127.0.0.1", 0), _GarbageHandler)):
        assert probe("127.0.0.1", port) is PortState.OCCUPIED


def test_health_endpoint_identifies_app(client: TestClient) -> None:
    response = client.get(HEALTH_PATH)
    assert response.status_code == 200
    assert response.json()["app"] == APP_NAME


@pytest.fixture()
def run_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., tuple[int, list[int]]]:
    """設定ファイルを隔離し、サーバーを実際には起動せずに CLI を呼ぶ。終了コードと起動したポートを返す。"""
    monkeypatch.delenv("HPH_ROOTS", raising=False)
    served: list[int] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **kw: served.append(kw["port"]))
    monkeypatch.setattr(cli, "create_app", lambda config: object())

    def run(state: PortState, *extra: str) -> tuple[int, list[int]]:
        monkeypatch.setattr(cli, "probe", lambda host, port: state)
        code = cli.main(["-c", str(tmp_path / "config.json"), "--no-browser", *extra])
        return code, served

    return run


def test_main_does_not_start_twice(
    run_cli: Callable[..., tuple[int, list[int]]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(PortState.RUNNING) == (cli.EXIT_ALREADY_RUNNING, [])
    assert "すでに起動しています" in capsys.readouterr().out


def test_main_refuses_port_used_by_other_app(run_cli: Callable[..., tuple[int, list[int]]]) -> None:
    assert run_cli(PortState.OCCUPIED) == (1, [])


def test_main_starts_and_prints_stop_guide(
    run_cli: Callable[..., tuple[int, list[int]]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(PortState.FREE) == (0, [8765])
    out = capsys.readouterr().out
    assert cli.STOP_GUIDE in out
    assert "停止しました" in out


@pytest.mark.parametrize(
    ("state", "expected_sleep", "expected_input"),
    [(PortState.RUNNING, [3.0], 0), (PortState.FREE, [3.0], 0), (PortState.OCCUPIED, [], 1)],
)
def test_pause_on_exit(
    run_cli: Callable[..., tuple[int, list[int]]],
    monkeypatch: pytest.MonkeyPatch,
    state: PortState,
    expected_sleep: list[float],
    expected_input: int,
) -> None:
    sleeps: list[float] = []
    prompts: list[str] = []
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    monkeypatch.setattr("builtins.input", prompts.append)
    run_cli(state, "--pause-on-exit", "3")
    assert sleeps == expected_sleep
    assert len(prompts) == expected_input


def test_main_bounds_graceful_shutdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("HPH_ROOTS", raising=False)
    monkeypatch.setattr(cli, "probe", lambda host, port: PortState.FREE)
    monkeypatch.setattr(cli, "create_app", lambda config: object())
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **kw: calls.append(kw))
    assert cli.main(["-c", str(tmp_path / "config.json"), "--no-browser"]) == 0
    assert calls[0]["timeout_graceful_shutdown"] == server.SHUTDOWN_TIMEOUT_SECONDS


def test_long_poll_returns_before_shutdown_timeout() -> None:
    assert server.WATCH_TIMEOUT_SECONDS < server.SHUTDOWN_TIMEOUT_SECONDS


def test_pause_on_exit_after_uvicorn_exits(
    run_cli: Callable[..., tuple[int, list[int]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise SystemExit(cli.EXIT_ALREADY_RUNNING)  # uvicorn 0.50 以降は起動失敗を 3 で返す

    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", prompts.append)
    monkeypatch.setattr(cli.uvicorn, "run", fail)
    assert run_cli(PortState.FREE, "--pause-on-exit", "3") == (1, [])
    assert len(prompts) == 1


def test_main_opens_browser_for_running_instance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: list[str] = []
    monkeypatch.delenv("HPH_ROOTS", raising=False)
    monkeypatch.setattr(cli, "probe", lambda host, port: PortState.RUNNING)
    monkeypatch.setattr(cli, "open_browser", opened.append)
    assert cli.main(["-c", str(tmp_path / "config.json"), "--port", "8899"]) == cli.EXIT_ALREADY_RUNNING
    assert opened == ["http://127.0.0.1:8899/"]


def test_browser_opens_only_after_server_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter([PortState.FREE, PortState.FREE, PortState.RUNNING])
    opened: list[str] = []
    monkeypatch.setattr(server, "probe", lambda host, port: next(states))
    monkeypatch.setattr(server, "open_browser", opened.append)
    monkeypatch.setattr(server, "BROWSER_POLL_SECONDS", 0)
    server.open_browser_when_ready("http://x/", "127.0.0.1", 1).join(timeout=5)
    assert opened == ["http://x/"]
    assert next(states, None) is None


def test_browser_gives_up_when_server_never_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(server, "probe", lambda host, port: PortState.FREE)
    monkeypatch.setattr(server, "open_browser", opened.append)
    monkeypatch.setattr(server, "BROWSER_POLL_SECONDS", 0)
    monkeypatch.setattr(server, "BROWSER_WAIT_SECONDS", 0.05)
    thread = server.open_browser_when_ready("http://x/", "127.0.0.1", 1)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert opened == []
