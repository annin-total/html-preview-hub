#!/usr/bin/env bash
# 依存関係の準備からサーバー起動までを 1 コマンドで行う。
#   ./start.sh                 … config.json（無ければ sample-docs）を対象に起動
#   ./start.sh ~/Documents/html … 指定フォルダを対象に起動して設定へ保存
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

if [ ! -d "$VENV" ]; then
  echo "→ 仮想環境を作成します: $VENV"
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1090
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ "$#" -gt 0 ]; then
  exec python -m hph "$@" --save
elif [ -f config.json ]; then
  exec python -m hph
else
  echo "→ config.json が無いため sample-docs を表示します"
  exec python -m hph ./sample-docs
fi
