import os

os.environ["API_KEY"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402

client = TestClient(app_module.app)
HEADERS = {"AccessToken": "test"}
executed = []


class FakeSql:
    def __init__(self, statement, database_name=None, params=None):
        self.call = (statement, database_name, params)

    def execute(self):
        executed.append(self.call)
        return []


app_module.SqlOperation = FakeSql


def test_health_is_public():
    assert client.get("/health").json() == {"status": "ok"}


def test_auth_required():
    assert client.get("/database/get").status_code == 403
    assert client.get("/database/get", headers={"AccessToken": "bad"}).status_code == 403
    assert client.get("/database/get", headers=HEADERS).json()["code"] == 200


def test_identifiers_are_validated():
    assert client.post("/database/create", headers=HEADERS,
                       json={"database_name": "x; DROP DATABASE y"}).status_code == 422
    assert client.get("/row/get/db/users;--", headers=HEADERS).status_code == 422
    assert client.post("/row/insert", headers=HEADERS, json={
        "database_name": "db", "table_name": "t", "values": {"a) VALUES (1); --": 1}
    }).status_code == 422
    assert client.post("/row/insert", headers=HEADERS, json={
        "database_name": "db", "table_name": "t", "values": {}
    }).status_code == 422


def test_row_update_uses_params():
    executed.clear()
    r = client.put("/row/update", headers=HEADERS, json={
        "database_name": "db", "table_name": "t", "row_id": 7, "values": {"name": "x'y"}
    })
    assert r.json()["code"] == 200
    assert executed == [("UPDATE t SET name=%s WHERE id=%s", "db", ("x'y", 7))]


def test_user_password_never_stored():
    uid = client.post("/user", headers=HEADERS, json={
        "username": "a", "email": "a@b.c", "password": "p"
    }).json()["data"]["id"]
    r = client.put(f"/user/{uid}", headers=HEADERS, json={"password": "new"})
    assert "password" not in r.json()["data"]
    assert client.delete(f"/user/{uid}", headers=HEADERS).json()["code"] == 200
    assert client.get(f"/user/{uid}", headers=HEADERS).json()["code"] == 404
