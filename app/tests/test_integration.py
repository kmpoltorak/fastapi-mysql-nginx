"""End-to-end tests against the running stack (nginx + app + MySQL).

Run: docker compose up -d --build --wait
     set -a; . ./.env; set +a
     INTEGRATION_URL=https://localhost python -m pytest app/tests/test_integration.py
"""
import json
import os
import ssl
import urllib.error
import urllib.request

import pyotp
import pytest

URL = os.getenv("INTEGRATION_URL")
pytestmark = pytest.mark.skipif(not URL, reason="INTEGRATION_URL not set")
SSL = ssl._create_unverified_context()  # self-signed certificate


def call(method, path, body=None, token=None, url=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request((url or URL) + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, context=SSL) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def login(username, password, totp=None):
    status, body = call("POST", "/login",
                        {"username": username, "password": password, "totp": totp})
    return body.get("access_token") if status == 200 else status


@pytest.fixture(scope="module")
def token():
    return login(os.getenv("ADMIN_USERNAME", "admin"), os.environ["ADMIN_PASSWORD"])


def test_http_redirects_to_https():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(URL.replace("https://", "http://") + "/health")
    assert e.value.code == 301


def test_auth(token):
    assert isinstance(token, str)
    assert login("admin", "wrong") == 401
    assert login("nobody", "wrong") == 401
    assert call("GET", "/database/get")[0] == 401


def test_database_flow(token):
    call("DELETE", "/database/delete", {"database_name": "it_db"}, token)
    assert call("POST", "/database/create", {"database_name": "it_db"}, token)[0] == 200
    assert call("POST", "/database/create", {"database_name": "it_db"}, token)[0] == 400
    assert call("POST", "/table/create", {
        "database_name": "it_db", "table_name": "person", "columns": [
            {"name": "pid", "params": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY"},
            {"name": "name", "params": "VARCHAR(255)"}]}, token)[0] == 200
    for body in ({"action": "add", "column_name": "age", "params": "INT DEFAULT 0"},
                 {"action": "rename", "column_name": "age", "new_column_name": "years"},
                 {"action": "drop", "column_name": "years"}):
        assert call("PUT", "/table/alter", {"database_name": "it_db", "table_name": "person",
                                            **body}, token)[0] == 200
    assert call("PUT", "/table/alter", {"database_name": "it_db", "table_name": "person",
                                        "action": "drop", "column_name": "nope"}, token)[0] == 400
    for name in ("Ann", "Bob", "Cid"):
        call("POST", "/row/insert", {"database_name": "it_db", "table_name": "person",
                                     "values": {"name": name}}, token)
    assert call("PUT", "/row/update", {
        "database_name": "it_db", "table_name": "person", "row_id": 1, "key_column": "pid",
        "values": {"name": "O'Brien"}}, token)[0] == 200
    status, body = call("GET", "/row/get/it_db/person?limit=2&offset=0", token=token)
    assert body["data"] == [[1, "O'Brien"], [2, "Bob"]]
    assert call("GET", "/row/get/it_db/missing", token=token)[0] == 400

    dump = call("POST", "/database/backup", {"database_name": "it_db"}, token)[1]["data"]
    call("DELETE", "/row/delete", {"database_name": "it_db", "table_name": "person",
                                   "row_id": 1, "key_column": "pid"}, token)
    assert call("POST", "/database/restore",
                {"database_name": "it_db", "sql_dump": dump}, token)[0] == 200
    assert len(call("GET", "/row/get/it_db/person", token=token)[1]["data"]) == 3
    assert call("DELETE", "/database/delete", {"database_name": "it_db"}, token)[0] == 200


def test_db_user_cannot_touch_system_or_auth_data(token):
    call("POST", "/database/create", {"database_name": "it_sec"}, token)
    for sql in ("SELECT * FROM mysql.user;", "SELECT * FROM api_auth.users;",
                "DROP DATABASE api_auth;", "CREATE USER x IDENTIFIED BY 'x';"):
        assert call("POST", "/database/restore",
                    {"database_name": "it_sec", "sql_dump": sql}, token)[0] == 400, sql
    call("DELETE", "/database/delete", {"database_name": "it_sec"}, token)


def test_users_and_totp(token):
    status, body = call("POST", "/user", {"username": "it_user", "email": "a@b.c",
                                          "password": "pw1"}, token)
    assert status == 200 and "password_hash" not in body["data"]
    user_id = body["data"]["id"]
    try:
        assert call("POST", "/user", {"username": "it_user", "email": "a@b.c",
                                      "password": "pw1"}, token)[0] == 400
        user_token = login("it_user", "pw1")
        secret = call("POST", "/auth/totp/setup", token=user_token)[1]["data"]["secret"]
        assert call("POST", "/auth/totp/enable",
                    {"secret": secret, "code": "abcdef"}, user_token)[0] == 400
        assert call("POST", "/auth/totp/enable",
                    {"secret": secret, "code": pyotp.TOTP(secret).now()}, user_token)[0] == 200
        assert login("it_user", "pw1") == 401
        assert isinstance(login("it_user", "pw1", pyotp.TOTP(secret).now()), str)
        assert call("GET", f"/user/{user_id}", token=token)[1]["data"]["totp_enabled"] is True
    finally:
        assert call("DELETE", f"/user/{user_id}", token=token)[0] == 200
    assert call("GET", f"/user/{user_id}", token=token)[0] == 404
