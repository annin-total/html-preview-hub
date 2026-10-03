"""OS のフォルダ選択画面を開き、選ばれたフォルダを返す。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    command = _command()
    if command is None:
        return PickResult("unavailable", message="この環境ではフォルダの選択画面を開けません")
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
    """zenity・kdialog は取り消しを終了コード 1 で返し、警告を stderr に出すことがある。"""
    if sys.platform == "darwin":
        return _MAC_CANCEL in err
    return returncode == 1


def _command() -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("osascript"):
        # activate しないと、選択画面がブラウザの背面に開くことがある
        return [
            "osascript",
            "-e",
            "activate",
            "-e",
            f'POSIX path of (choose folder with prompt "{PICK_PROMPT}")',
        ]
    if sys.platform == "win32" and shutil.which("powershell"):
        return ["powershell", "-NoProfile", "-STA", "-Command", _WINDOWS_SCRIPT]
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--directory", f"--title={PICK_PROMPT}"]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory", os.path.expanduser("~"), "--title", PICK_PROMPT]
    return None


def _strip_trailing_sep(path: str) -> str:
    return path.rstrip("/\\") if len(path.rstrip("/\\")) > 2 else path


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
