"""OS のフォルダ選択画面。"""

from __future__ import annotations

import subprocess
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import hph.picker as picker
import hph.server as server
from hph.config import Config


def _completed(code: int, out: bytes = b"", err: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


@pytest.fixture()
def fake_run(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(picker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    return calls


def _use(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    def run(command: list[str], **_: object) -> object:
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(picker.subprocess, "run", run)


def test_selected_path_is_trimmed(monkeypatch: pytest.MonkeyPatch, fake_run: list) -> None:
    _use(monkeypatch, _completed(0, "/Users/me/資料/\n".encode()))
    assert picker.pick_folder().to_json() == {"status": "selected", "path": "/Users/me/資料"}


def test_cancel_on_macos(monkeypatch: pytest.MonkeyPatch, fake_run: list) -> None:
    _use(monkeypatch, _completed(1, err=b"execution error: User canceled. (-128)"))
    assert picker.pick_folder().status == "cancelled"


def test_timeout_is_cancel(monkeypatch: pytest.MonkeyPatch, fake_run: list) -> None:
    _use(monkeypatch, subprocess.TimeoutExpired(["osascript"], 1))
    assert picker.pick_folder().status == "cancelled"


def test_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch, fake_run: list) -> None:
    _use(monkeypatch, _completed(1, err=b"not authorized"))
    assert picker.pick_folder().status == "unavailable"


def test_no_tool_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setattr(picker.shutil, "which", lambda name: None)
    assert picker.pick_folder().status == "unavailable"


@pytest.mark.parametrize(
    ("platform", "tool"), [("darwin", "osascript"), ("win32", "powershell"), ("linux", "zenity")]
)
def test_command_per_platform(monkeypatch: pytest.MonkeyPatch, platform: str, tool: str) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(picker.sys, "platform", platform)
    monkeypatch.setattr(picker.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(picker.subprocess, "run", lambda cmd, **_: seen.append(cmd) or _completed(0, b"/x"))
    picker.pick_folder()
    assert seen[0][0] == tool


def test_windows_output_is_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "win32")
    monkeypatch.setattr(picker.shutil, "which", lambda name: name)
    _use(monkeypatch, _completed(0, "C:\\Users\\me\\資料\r\n".encode()))
    assert picker.pick_folder().path == "C:\\Users\\me\\資料"


def test_endpoint_rejects_non_loopback(config: Config, tmp_path) -> None:
    from hph.store import UserStore

    app = server.create_app(config, store=UserStore(tmp_path / "state"))
    with TestClient(app, client=("192.168.0.10", 50000)) as remote:
        assert remote.post("/api/pick-folder").status_code == 403


def test_endpoint_returns_result_and_rejects_second(
    config: Config, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hph.store import UserStore

    opened, release = threading.Event(), threading.Event()

    def slow_pick() -> picker.PickResult:
        opened.set()
        release.wait(5)
        return picker.PickResult("selected", path="/x")

    monkeypatch.setattr(server, "pick_folder", slow_pick)
    app = server.create_app(config, store=UserStore(tmp_path / "state"))
    with TestClient(app, client=("127.0.0.1", 50000)) as local:
        results: list[object] = []
        first = threading.Thread(target=lambda: results.append(local.post("/api/pick-folder")))
        first.start()
        assert opened.wait(5)
        assert local.post("/api/pick-folder").status_code == 409
        release.set()
        first.join(5)
        assert results[0].json() == {"status": "selected", "path": "/x"}
