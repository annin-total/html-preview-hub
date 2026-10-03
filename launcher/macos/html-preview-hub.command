#!/bin/bash
# デスクトップのエイリアスから起動するランチャー。サーバーの終了後にこのウインドウを閉じる。
# 仮想環境とエイリアスは同じフォルダの install.sh で準備する。
cd "$(dirname "$0")/../.." || exit 1

if [ -x .venv/bin/python ]; then
  .venv/bin/python -m hph --pause-on-exit 3
else
  echo "仮想環境がありません。先に launcher/macos/install.sh を実行してください。"
  read -r -p "Enter キーを押すとこのウインドウを閉じます。"
fi

# 実行中に閉じると確認ダイアログが出るため、シェルの終了を待ってから閉じる。
TTY_NAME=$(tty)
nohup osascript -e 'on run argv' -e 'delay 0.5' \
  -e 'tell application "Terminal" to close (every window whose tty of selected tab is (item 1 of argv))' \
  -e 'end run' "$TTY_NAME" >/dev/null 2>&1 &
