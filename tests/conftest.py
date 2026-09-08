"""テスト共通のフィクスチャ。"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hph.config import Config
from hph.server import create_app
from hph.store import UserStore


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """テスト用のディレクトリツリーを組み立てる。"""
    root = tmp_path / "docs"
    (root / "alpha" / "assets").mkdir(parents=True)
    (root / "beta").mkdir(parents=True)
    (root / "node_modules").mkdir(parents=True)

    (root / "alpha" / "index.html").write_text(
        "<html><head><title>アルファの概要</title></head><body>"
        '<link rel="stylesheet" href="./assets/style.css"><p>hello</p></body></html>',
        encoding="utf-8",
    )
    (root / "alpha" / "assets" / "style.css").write_text("body{color:#000}", encoding="utf-8")
    (root / "alpha" / "no-title.html").write_text(
        "<html><body><h1>H1 から拾うタイトル</h1></body></html>", encoding="utf-8"
    )
    (root / "beta" / "broken.html").write_text("<html><head><title>壊れた", encoding="utf-8")
    (root / "beta" / "paper.tex").write_text(
        "\\documentclass{article}\n\\title{テスト論文}\n\\begin{document}\\maketitle\\end{document}\n",
        encoding="utf-8",
    )
    (root / "beta" / "fragment.tex").write_text(
        "\\section{断片}\nこのファイルは \\input される想定。\n", encoding="utf-8"
    )
    (root / "beta" / "notes.txt").write_text("対象外の拡張子", encoding="utf-8")
    (root / "node_modules" / "ignored.html").write_text("<title>無視される</title>", encoding="utf-8")
    return root


@pytest.fixture()
def config(tree: Path, tmp_path: Path) -> Config:
    cfg = Config.from_dict(
        {
            "roots": [{"path": str(tree), "name": "docs"}],
            "tex_cache_dir": str(tmp_path / "tex-cache"),
        }
    )
    cfg.path = tmp_path / "config.json"
    cfg.watch_interval_seconds = 0  # テスト中はバックグラウンド監視を止める
    cfg.tex_use_latexmk = False  # 実行環境に依存しないよう latexmk は使わない
    cfg.tex_max_passes = 1
    return cfg


# ----------------------------------------------------------------------
# LaTeX エンジンのスタブ
# ----------------------------------------------------------------------
#: 外部コマンドに依存しないよう、シェル組み込みだけで PDF とログを書くスタブ。
STUB_TEMPLATE = """#!/bin/sh
out="."
tex=""
for arg in "$@"; do
  case "$arg" in
    -output-directory=*) out="${arg#-output-directory=}" ;;
    *.tex) tex="$arg" ;;
  esac
done
stem="${tex##*/}"
stem="${stem%.tex}"
printf 'stub log for %s\n{LOG}' "$tex" > "$out/$stem.log"
{BODY}
"""
WRITE_PDF = (
    "printf '%%PDF-1.4\\n1 0 obj<</Type/Catalog>>endobj\\ntrailer<</Root 1 0 R>>\\n%%%%EOF\\n'"
    ' > "$out/$stem.pdf"'
)


@pytest.fixture()
def install_tex_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """スタブエンジンを PATH の先頭へ差し込むファクトリを返す。"""

    def install(name: str = "pdflatex", *, body: str = WRITE_PDF, log: str = "") -> Path:
        bin_dir = tmp_path / "stub-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        script = bin_dir / name
        script.write_text(STUB_TEMPLATE.replace("{BODY}", body).replace("{LOG}", log), encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        return script

    return install


@pytest.fixture()
def client(config: Config, tmp_path: Path) -> Iterator[TestClient]:
    store = UserStore(tmp_path / "state")
    with TestClient(create_app(config, store=store)) as test_client:
        yield test_client
