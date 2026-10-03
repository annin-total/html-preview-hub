"""ファイルの解決と配信（ルート消失・ディレクトリ・MIME・文字コード）の検証。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hph.config import Config


def _root_id(client: TestClient) -> str:
    return client.get("/api/index").json()["roots"][0]["id"]


def test_file_whose_root_was_removed_is_404(client: TestClient, config: Config) -> None:
    file_id = f"{_root_id(client)}:alpha/index.html"
    config.roots.clear()  # インデックスには残ったまま、ルートだけが消えた状態
    response = client.get("/api/source", params={"fileId": file_id})
    assert response.status_code == 404
    assert response.json()["error"] == "ルートが見つかりません"


def test_raw_directory_serves_its_index_html(client: TestClient) -> None:
    root_id = _root_id(client)
    page = client.get(f"/raw/{root_id}/alpha/")
    assert page.status_code == 200
    assert "アルファの概要" in page.text
    assert client.get(f"/raw/{root_id}/beta/").status_code == 404


def test_raw_serves_javascript_as_text_javascript(client: TestClient, tree: Path) -> None:
    (tree / "alpha" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    response = client.get(f"/raw/{_root_id(client)}/alpha/assets/app.js")
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"


def test_source_decodes_declared_charset(client: TestClient, tree: Path) -> None:
    html = '<meta charset="shift_jis"><title>日本語</title>'
    (tree / "alpha" / "sjis.html").write_bytes(html.encode("shift_jis"))
    client.post("/api/rescan")
    file_id = f"{_root_id(client)}:alpha/sjis.html"
    assert client.get("/api/source", params={"fileId": file_id}).json()["text"] == html
