"""HTTP API とファイル配信の検証。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hph.config import Config


def _index(client: TestClient) -> dict:
    response = client.get("/api/index")
    assert response.status_code == 200
    return response.json()


def test_index_lists_folders_and_files(client: TestClient) -> None:
    payload = _index(client)
    assert payload["stats"]["fileCount"] == 5
    assert {f["name"] for f in payload["folders"]} == {"alpha", "beta"}
    assert payload["roots"][0]["name"] == "docs"


def test_raw_serves_html_and_relative_assets(client: TestClient) -> None:
    payload = _index(client)
    root_id = payload["roots"][0]["id"]
    page = client.get(f"/raw/{root_id}/alpha/index.html")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    asset = client.get(f"/raw/{root_id}/alpha/assets/style.css")
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("text/css")


def test_raw_blocks_traversal(client: TestClient) -> None:
    root_id = _index(client)["roots"][0]["id"]
    response = client.get(f"/raw/{root_id}/../../etc/passwd")
    assert response.status_code in (403, 404)
    assert "etc/passwd" not in response.text or "見つかりません" in response.text


def test_missing_file_returns_error_page_not_crash(client: TestClient) -> None:
    root_id = _index(client)["roots"][0]["id"]
    response = client.get(f"/raw/{root_id}/alpha/nope.html")
    assert response.status_code == 404
    assert "プレビューを表示できません" in response.text


def test_unknown_root_returns_404(client: TestClient) -> None:
    response = client.get("/raw/deadbeef/index.html")
    assert response.status_code == 404


def test_absolute_asset_is_resolved_via_referer(client: TestClient) -> None:
    root_id = _index(client)["roots"][0]["id"]
    response = client.get(
        "/alpha/assets/style.css",
        headers={"referer": f"http://testserver/raw/{root_id}/alpha/index.html"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_favorites_and_hidden_roundtrip(client: TestClient) -> None:
    payload = _index(client)
    file_id = payload["files"][0]["id"]
    folder_id = payload["folders"][0]["id"]
    assert client.post("/api/user/favorites", json={"fileId": file_id}).json()["added"] is True
    assert client.post("/api/user/hidden", json={"folderId": folder_id}).json()["added"] is True
    state = _index(client)["userState"]
    assert state["favorites"] == [file_id]
    assert state["hiddenFolders"] == [folder_id]


def test_source_endpoint_returns_text(client: TestClient) -> None:
    file_id = next(f["id"] for f in _index(client)["files"] if f["relPath"].endswith("index.html"))
    payload = client.get("/api/source", params={"fileId": file_id}).json()
    assert "アルファの概要" in payload["text"]


def test_source_endpoint_404_for_unknown_file(client: TestClient) -> None:
    assert client.get("/api/source", params={"fileId": "x:y"}).status_code == 404


def test_rescan_picks_up_new_file(client: TestClient, tree: Path) -> None:
    (tree / "alpha" / "added.html").write_text("<title>あとから追加</title>", encoding="utf-8")
    payload = client.post("/api/rescan").json()
    assert any(f["title"] == "あとから追加" for f in payload["files"])
    assert payload["revision"] >= 1


def test_watch_returns_after_timeout_without_change(client: TestClient, monkeypatch) -> None:
    import hph.server as server

    monkeypatch.setattr(server, "WATCH_TIMEOUT_SECONDS", 0.05)
    response = client.get("/api/index/watch", params={"revision": _index(client)["revision"]})
    assert response.status_code == 200
    assert response.json()["changed"] is False


def test_root_crud(client: TestClient, tmp_path: Path, config: Config) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "page.html").write_text("<title>追加ルート</title>", encoding="utf-8")
    added = client.post("/api/roots", json={"path": str(extra), "name": "extra"})
    assert added.status_code == 200
    root_id = added.json()["root"]["id"]
    assert any(r["id"] == root_id for r in _index(client)["roots"])
    assert client.delete(f"/api/roots/{root_id}").status_code == 200
    assert all(r["id"] != root_id for r in _index(client)["roots"])


def test_adding_missing_root_returns_400(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/roots", json={"path": str(tmp_path / "ghost")})
    assert response.status_code == 400
    assert "見つかりません" in response.json()["error"]


def test_browse_lists_directories_only(client: TestClient, tree: Path) -> None:
    payload = client.get("/api/browse", params={"path": str(tree)}).json()
    assert {e["name"] for e in payload["entries"]} == {"alpha", "beta", "node_modules"}


def test_config_update_changes_scan_result(client: TestClient) -> None:
    response = client.put("/api/config", json={"include_extensions": [".txt"]})
    assert response.status_code == 200
    payload = _index(client)
    assert payload["stats"]["fileCount"] == 1
    assert payload["files"][0]["name"] == "notes.txt"


def test_spa_shell_and_static_assets(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200


def test_unknown_path_without_referer_is_404(client: TestClient) -> None:
    assert client.get("/totally/unknown").status_code == 404


def test_head_request_on_raw_is_allowed(client: TestClient) -> None:
    """フロントエンドはプレビュー前に HEAD で到達性を確認する。"""
    root_id = _index(client)["roots"][0]["id"]
    response = client.head(f"/raw/{root_id}/alpha/index.html")
    assert response.status_code == 200


# ----------------------------------------------------------------------
# LaTeX
# ----------------------------------------------------------------------
def test_index_marks_file_kind(client: TestClient) -> None:
    kinds = {f["relPath"]: f["kind"] for f in _index(client)["files"]}
    assert kinds["beta/paper.tex"] == "tex"
    assert kinds["alpha/index.html"] == "html"


def test_tex_status_reports_environment(client: TestClient) -> None:
    payload = client.get("/api/tex/status").json()
    assert payload["enabled"] is True
    assert isinstance(payload["engines"], list)
    assert payload["configuredEngine"] == "auto"


def test_tex_compile_rejects_non_tex_file(client: TestClient) -> None:
    file_id = next(f["id"] for f in _index(client)["files"] if f["relPath"].endswith(".html"))
    response = client.post("/api/tex/compile", json={"fileId": file_id})
    assert response.status_code == 400


def test_tex_compile_unknown_file(client: TestClient) -> None:
    assert client.post("/api/tex/compile", json={"fileId": "x:y.tex"}).status_code == 404


def test_tex_fragment_is_reported(client: TestClient) -> None:
    r"""`\documentclass` が無い断片はコンパイルせず、その旨を返す。"""
    file_id = next(f["id"] for f in _index(client)["files"] if f["relPath"] == "beta/fragment.tex")
    payload = client.post("/api/tex/compile", json={"fileId": file_id}).json()
    assert payload["status"] == "fragment"
    assert "documentclass" in payload["message"]


def test_tex_compile_and_serve_pdf(client: TestClient, install_tex_stub) -> None:
    install_tex_stub()
    file_id = next(f["id"] for f in _index(client)["files"] if f["relPath"] == "beta/paper.tex")
    payload = client.post("/api/tex/compile", json={"fileId": file_id}).json()
    assert payload["status"] == "ok", payload
    pdf = client.get(payload["pdfUrl"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    # 2 回目はキャッシュから返る
    assert client.post("/api/tex/compile", json={"fileId": file_id}).json()["cached"] is True


def test_tex_pdf_rejects_unknown_fingerprint(client: TestClient) -> None:
    file_id = next(f["id"] for f in _index(client)["files"] if f["relPath"] == "beta/paper.tex")
    response = client.get("/api/tex/pdf", params={"fileId": file_id, "v": "../../etc/passwd"})
    assert response.status_code == 404
