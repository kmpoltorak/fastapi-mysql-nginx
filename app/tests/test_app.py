import os

os.environ["JWT_SECRET"] = "unit-test-secret-at-least-32-bytes-long"

import jwt  # noqa: E402
import pyotp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import auth  # noqa: E402

client = TestClient(app_module.app)  # no `with` -> lifespan (DB bootstrap) doesn't run
HEADERS = {"Authorization": f"Bearer {auth.create_access_token('tester')}"}
executed = []


def fake_query(statement, database_name=None, params=None, auth=False):
    executed.append((statement, database_name, params))
    return []


app_module.query = auth.query = fake_query


def test_health_is_public():
    assert client.get("/health").json() == {"status": "ok"}


def test_token_required():
    assert client.get("/database/get").status_code == 401
    assert client.get("/database/get", headers={"Authorization": "Bearer bad"}).status_code == 401
    expired = jwt.encode({"sub": "x", "exp": 0}, os.environ["JWT_SECRET"], "HS256")
    assert client.get("/database/get",
                      headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": "x"}, "another-secret-at-least-32-bytes-long", "HS256")
    assert client.get("/database/get",
                      headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/database/get", headers=HEADERS).status_code == 200


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
    assert client.request("DELETE", "/row/delete", headers=HEADERS, json={
        "database_name": "db", "table_name": "t", "row_id": 1, "key_column": "id OR 1=1"
    }).status_code == 422


def test_row_queries_use_params():
    executed.clear()
    client.put("/row/update", headers=HEADERS, json={
        "database_name": "db", "table_name": "t", "row_id": 7, "values": {"name": "x'y"},
        "key_column": "uid"
    })
    client.get("/row/get/db/t?limit=5&offset=10", headers=HEADERS)
    assert executed == [
        ("UPDATE t SET name=%s WHERE uid=%s", "db", ("x'y", 7)),
        ("SELECT * FROM t LIMIT %s OFFSET %s", "db", (5, 10)),
    ]
    assert client.get("/row/get/db/t?limit=5000", headers=HEADERS).status_code == 422


def test_password_hashing():
    stored = auth.hash_password("secret")
    assert stored.startswith("scrypt$") and "secret" not in stored
    assert auth.verify_password("secret", stored)
    assert not auth.verify_password("Secret", stored)
    assert stored != auth.hash_password("secret")  # random salt


def test_totp():
    secret = pyotp.random_base32()
    step = auth.totp_step(secret, pyotp.TOTP(secret).now())
    assert step is not None
    assert auth.totp_step(secret, pyotp.TOTP(secret).now(), last_step=step) is None  # replay
    assert auth.totp_step(secret, "abcdef") is None
    assert auth.totp_step(secret, None) is None


def test_api_keys():
    key = {"Authorization": "Bearer mk_unknown"}
    assert client.get("/database/get", headers=key).status_code == 401  # not in DB
    for method, path in (("GET", "/user"), ("POST", "/auth/api-keys"),
                         ("POST", "/auth/totp/setup")):
        assert client.request(method, path, headers=key, json={"name": "x"}).status_code == 403


def test_alter_table():
    executed.clear()
    base = {"database_name": "db", "table_name": "t", "column_name": "age"}
    for body in ({"action": "add", "params": "INT"}, {"action": "modify", "params": "BIGINT"},
                 {"action": "rename", "new_column_name": "years"}, {"action": "drop"}):
        assert client.put("/table/alter", headers=HEADERS, json={**base, **body}).status_code == 200
    assert [sql for sql, *_ in executed] == [
        "ALTER TABLE t ADD COLUMN age INT", "ALTER TABLE t MODIFY COLUMN age BIGINT",
        "ALTER TABLE t RENAME COLUMN age TO years", "ALTER TABLE t DROP COLUMN age"]
    for bad in ({"action": "add"}, {"action": "rename"}, {"action": "truncate"},
                {"action": "rename", "new_column_name": "x;--"}):
        assert client.put("/table/alter", headers=HEADERS, json={**base, **bad}).status_code == 422
