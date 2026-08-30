"""テスト共通のフィクスチャ。"""

from __future__ import annotations

import sys
from collections.abc import Iterator
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
    (root / "beta" / "notes.txt").write_text("対象外の拡張子", encoding="utf-8")
    (root / "node_modules" / "ignored.html").write_text("<title>無視される</title>", encoding="utf-8")
    return root


@pytest.fixture()
def config(tree: Path, tmp_path: Path) -> Config:
    cfg = Config.from_dict({"roots": [{"path": str(tree), "name": "docs"}]})
    cfg.path = tmp_path / "config.json"
    cfg.watch_interval_seconds = 0  # テスト中はバックグラウンド監視を止める
    return cfg


@pytest.fixture()
def client(config: Config, tmp_path: Path) -> Iterator[TestClient]:
    store = UserStore(tmp_path / "state")
    with TestClient(create_app(config, store=store)) as test_client:
        yield test_client
