"""OS のフォルダ選択画面を開き、選ばれたフォルダを返す。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

PICK_TIMEOUT_SECONDS = 600.0
PICK_PROMPT = "追加するフォルダを選択してください"
#: macOS で利用者がキャンセルしたときのエラー番号。
_MAC_CANCEL = "-128"


@dataclass(frozen=True)
class PickResult:
    """選択の結果。`status` は selected / cancelled / unavailable のいずれか。"""

    status: str
    path: str = ""
    message: str = ""

    def to_json(self) -> dict[str, str]:
        """API レスポンス用の辞書へ変換する。"""
        body = {"status": self.status}
        if self.status == "selected":
            body["path"] = self.path
        if self.status == "unavailable":
            body["message"] = self.message
        return body


def pick_folder(timeout: float = PICK_TIMEOUT_SECONDS) -> PickResult:
    """選択画面を開き、閉じられるまで待つ（ブロッキング。呼び出し側でスレッドに逃がす）。"""
    commands = _commands()
    if not commands:
        return PickResult("unavailable", message="この環境ではフォルダの選択画面を開けません")
    deadline = time.monotonic() + timeout
    result = PickResult("unavailable")
    for command in commands:
        result = _run(command, max(deadline - time.monotonic(), 0.0))
        if result.status != "unavailable":
            return result
    return result


def _run(command: list[str], timeout: float) -> PickResult:
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired:
        return PickResult("cancelled")
    except OSError as exc:
        return PickResult("unavailable", message=f"フォルダの選択画面を開けません: {exc}")
    out = completed.stdout.decode("utf-8", errors="replace").strip()
    err = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode == 0:
        return PickResult("selected", path=_strip_trailing_sep(out)) if out else PickResult("cancelled")
    if not err or _is_cancel(completed.returncode, err):
        return PickResult("cancelled")
    return PickResult("unavailable", message=f"フォルダの選択画面を開けません: {err[:200]}")


def _is_cancel(returncode: int, err: str) -> bool:
    """zenity・kdialog は取り消しを終了コード 1 で返し、stderr に警告も出す（Windows は取り消しでも 0）。"""
    if sys.platform == "darwin":
        return _MAC_CANCEL in err
    return sys.platform != "win32" and returncode == 1


def _commands() -> list[list[str]]:
    """試す順に並べた起動コマンド。前のものが開けなかったときだけ次を使う。"""
    if sys.platform == "darwin" and shutil.which("osascript"):
        return [_osascript(_MAC_VIA_SYSTEM_EVENTS), _osascript(_MAC_DIRECT)]
    if sys.platform == "win32" and shutil.which("powershell"):
        return [["powershell", "-NoProfile", "-STA", "-Command", _WINDOWS_SCRIPT]]
    if sys.platform not in ("darwin", "win32") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return []  # 表示環境が無いと zenity は取り消しと同じ終了コード 1 で失敗する
    if shutil.which("zenity"):
        return [["zenity", "--file-selection", "--directory", f"--title={PICK_PROMPT}"]]
    if shutil.which("kdialog"):
        return [["kdialog", "--getexistingdirectory", os.path.expanduser("~"), "--title", PICK_PROMPT]]
    return []


def _osascript(lines: tuple[str, ...]) -> list[str]:
    return ["osascript", *(arg for line in lines for arg in ("-e", line))]


def _strip_trailing_sep(path: str) -> str:
    return path.rstrip("/\\") if len(path.rstrip("/\\")) > 2 else path


# osascript 自身が開く画面は英語表示で、前面に出す activate に約 2 秒かかる。
# 日本語化されていて余計なウインドウを持たない System Events に開かせ、閉じたら元のアプリへ前面を戻す。
# 「オートメーション」の許可が無いなどで失敗したら _MAC_DIRECT で開き直す。
_MAC_VIA_SYSTEM_EVENTS = (
    "set frontApp to path to frontmost application as text",
    "try",
    'tell application "System Events"',
    "activate",
    f'set chosen to choose folder with prompt "{PICK_PROMPT}"',
    "end tell",
    "on error msg number n",
    "tell application frontApp to activate",
    "error msg number n",
    "end try",
    "tell application frontApp to activate",
    "return POSIX path of chosen",
)
# activate しないと、選択画面がブラウザの背面に開くことがある
_MAC_DIRECT = ("activate", f'POSIX path of (choose folder with prompt "{PICK_PROMPT}")')

# 標準出力を UTF-8 にしないと、日本語のフォルダ名が cp932 で化ける
_WINDOWS_SCRIPT = f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{{TopMost = $true}}
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{PICK_PROMPT}'
$ok = [System.Windows.Forms.DialogResult]::OK
if ($dialog.ShowDialog($owner) -eq $ok) {{ [Console]::Write($dialog.SelectedPath) }}
"""
