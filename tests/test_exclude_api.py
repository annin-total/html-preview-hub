"""除外ルールの API。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from hph.config import Config

DRAFT = {"target": "folder", "match": "equals", "value": "alpha"}


def _root_id(client: TestClient) -> str:
    return client.get("/api/index").json()["roots"][0]["id"]


def test_global_exclude_is_saved_and_applied(client: TestClient, config: Config) -> None:
    response = client.put("/api/config", json={"exclude": [DRAFT]})
    assert response.status_code == 200
    assert response.json()["config"]["exclude"] == [DRAFT]
    names = {f["name"] for f in client.get("/api/index").json()["files"]}
    assert "index.html" not in names
    saved = json.loads(config.path.read_text(encoding="utf-8"))
    assert saved["exclude"] == [DRAFT]


def test_root_exclude_is_saved_and_listed(client: TestClient) -> None:
    root_id = _root_id(client)
    response = client.patch(f"/api/roots/{root_id}", json={"exclude": [DRAFT]})
    assert response.status_code == 200
    assert response.json()["root"]["exclude"] == [DRAFT]
    index = client.get("/api/index").json()
    assert index["roots"][0]["exclude"] == [DRAFT]
    assert "index.html" not in {f["name"] for f in index["files"]}


def test_rename_still_works_without_exclude(client: TestClient) -> None:
    root_id = _root_id(client)
    client.patch(f"/api/roots/{root_id}", json={"exclude": [DRAFT]})
    response = client.patch(f"/api/roots/{root_id}", json={"name": "資料"})
    assert response.json()["root"] == {**response.json()["root"], "name": "資料", "exclude": [DRAFT]}


def test_invalid_rule_is_400_and_not_saved(client: TestClient, config: Config) -> None:
    bad = {"target": "folder", "match": "regex", "value": ".*"}
    assert client.put("/api/config", json={"exclude": [bad]}).status_code == 400
    response = client.patch(f"/api/roots/{_root_id(client)}", json={"exclude": [bad]})
    assert response.status_code == 400
    assert not config.path.exists()  # どちらの失敗でも保存しない


def test_patch_unknown_root_is_404(client: TestClient) -> None:
    assert client.patch("/api/roots/deadbeef", json={"exclude": []}).status_code == 404
