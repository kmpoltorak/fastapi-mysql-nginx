"""End-to-end tests against the running stack (nginx + app + MySQL).

Run: docker compose up -d --build --wait
     set -a; . ./.env; set +a
     INTEGRATION_URL=https://localhost python -m pytest app/tests/test_integration.py
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

import pyotp
import pytest

URL = os.getenv("INTEGRATION_URL")
HTTP_URL = os.getenv("INTEGRATION_HTTP_URL", (URL or "").replace("https://", "http://"))
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


@pytest.fixture(scope="module")
def token():
    status, body = call("POST", "/auth/token", {
        "client_id": os.getenv("API_CLIENT_ID", "app"),
        "client_secret": os.environ["API_CLIENT_SECRET"]})
    assert status == 200 and body["expires_in"] == 900
    return body["access_token"]


def user_login(token, username, password, totp=None):
    return call("POST", "/user/login",
                {"username": username, "password": password, "totp": totp}, token)


def test_http_redirects_to_https():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(HTTP_URL + "/health")
    assert e.value.code == 301


def test_client_auth(token):
    assert call("POST", "/auth/token", {"client_id": "app", "client_secret": "wrong"})[0] == 401
    assert call("POST", "/auth/token", {"client_id": "nobody", "client_secret": "x"})[0] == 401
    assert call("GET", "/database/get")[0] == 401
    assert call("GET", "/database/get", token=token)[0] == 200


def test_clients(token):
    status, body = call("POST", "/auth/clients", {"client_id": "it-script"}, token)
    assert status == 200
    status, new = call("POST", "/auth/token", {"client_id": "it-script",
                                               "client_secret": body["data"]["client_secret"]})
    assert status == 200
    ids = [c["client_id"] for c in call("GET", "/auth/clients", token=token)[1]["data"]]
    assert "it-script" in ids
    assert call("DELETE", "/auth/clients/it-script", token=new["access_token"])[0] == 400
    assert call("DELETE", "/auth/clients/it-script", token=token)[0] == 200
    assert call("POST", "/auth/token", {"client_id": "it-script",
                                        "client_secret": body["data"]["client_secret"]})[0] == 401


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


def test_user_login_totp_and_lockout(token):
    status, body = call("POST", "/user", {"username": "it_user", "email": "a@b.c",
                                          "password": "pw1"}, token)
    assert status == 200 and "password_hash" not in body["data"]
    user_id = body["data"]["id"]
    try:
        assert call("POST", "/user", {"username": "it_user", "email": "a@b.c",
                                      "password": "pw1"}, token)[0] == 400
        status, body = user_login(token, "it_user", "pw1")
        assert status == 200 and body["data"]["id"] == user_id
        assert user_login(token, "it_user", "bad")[0] == 401
        assert user_login(token, "nobody", "bad")[0] == 401

        # TOTP
        secret = call("POST", f"/user/{user_id}/totp/setup", token=token)[1]["data"]["secret"]
        assert call("POST", f"/user/{user_id}/totp/enable",
                    {"secret": secret, "code": "abcdef"}, token)[0] == 400
        totp = pyotp.TOTP(secret)
        assert call("POST", f"/user/{user_id}/totp/enable",
                    {"secret": secret, "code": totp.now()}, token)[0] == 200
        status, body = user_login(token, "it_user", "pw1")
        assert status == 401 and body["detail"] == "TOTP code required"
        assert user_login(token, "it_user", "pw1", totp.now())[0] == 401  # used by enable
        next_code = totp.at(time.time() + 30)  # still inside the clock drift window
        assert user_login(token, "it_user", "pw1", next_code)[0] == 200
        assert user_login(token, "it_user", "pw1", next_code)[0] == 401  # replay
        assert call("GET", f"/user/{user_id}", token=token)[1]["data"]["totp_enabled"] is True
        assert call("DELETE", f"/user/{user_id}/totp", token=token)[0] == 200
        assert user_login(token, "it_user", "pw1")[0] == 200

        # lockout after 5 failed attempts, password change unlocks
        for _ in range(5):
            assert user_login(token, "it_user", "bad")[0] == 401
        assert user_login(token, "it_user", "pw1")[0] == 423
        assert call("GET", f"/user/{user_id}", token=token)[1]["data"]["locked"] is True
        assert call("PUT", f"/user/{user_id}", {"password": "pw2"}, token)[0] == 200
        assert user_login(token, "it_user", "pw2")[0] == 200
    finally:
        assert call("DELETE", f"/user/{user_id}", token=token)[0] == 200
    assert call("GET", f"/user/{user_id}", token=token)[0] == 404
