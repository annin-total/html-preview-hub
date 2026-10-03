#!/bin/bash
# 仮想環境と依存を準備し、デスクトップにランチャーのエイリアスを置く。依存を更新したときも再実行する。
set -euo pipefail
cd "$(dirname "$0")/../.."

PYTHON="${PYTHON:-python3}"
ALIAS_NAME="html-preview-hub"
LAUNCHER="$PWD/launcher/macos/html-preview-hub.command"

[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
chmod +x "$LAUNCHER"

# 既存のエイリアスはゴミ箱へ移してから作り直す（エイリアス以外の同名ファイルがあれば失敗する）
osascript - "$LAUNCHER" "$ALIAS_NAME" >/dev/null <<'APPLESCRIPT'
on run argv
  set launcher to POSIX file (item 1 of argv) as alias
  set aliasName to item 2 of argv
  tell application "Finder"
    set desk to path to desktop folder
    if exists alias file aliasName of desk then delete alias file aliasName of desk
    make new alias file at desk to launcher with properties {name:aliasName}
  end tell
end run
APPLESCRIPT
echo "デスクトップに「${ALIAS_NAME}」を作成しました。ダブルクリックで起動します。"
