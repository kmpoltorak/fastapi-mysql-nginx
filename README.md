# FastAPI + MySQL + Nginx

A REST API (FastAPI) for managing MySQL databases, tables, rows and
application users, behind Nginx over HTTPS, all in Docker Compose. It sits
between an application and the database: the application authenticates with a
client JWT, and the API also stores and verifies the application's users
(password plus optional TOTP). It is a development and learning stack.

```text
$ TOKEN=$(curl -sk -X POST https://localhost/auth/token -H 'Content-Type: application/json' \
    -d '{"client_id": "app", "client_secret": "<API_CLIENT_SECRET>"}' | jq -r .access_token)
$ curl -sk https://localhost/row/get/shop/person -H "Authorization: Bearer $TOKEN"
{"code":200,"message":"Rows fetched","data":[[1,"Ann"]]}
$ curl -sk -X POST https://localhost/database/restore -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' -d '{"database_name": "shop", "sql_dump": "\\! id"}'
{"detail":"mysql error: ERROR at line 1: Not allowed in the sandbox mode\n"}
```

- Least-privilege MySQL users: `api` can manage any database but cannot read `mysql`, `sys` or `api_auth`, create users or grant privileges; `api_auth` can only read and write the `clients` and `users` tables. Even arbitrary SQL sent to `/database/restore` cannot read password hashes or create a client.
- Restores run in the MariaDB client's `--sandbox` mode with `--local-infile=0`, as a non-root user, with only `PATH` and the `api` password in the environment. The Docker build fails if the client lacks `--sandbox`.
- Passwords and client secrets are hashed with scrypt and never returned; a client secret is shown once, on creation.
- Each TOTP code works once, even for concurrent logins. Five wrong passwords or codes lock a user for 15 minutes.
- The stack refuses to start with a missing secret. Nginx serves TLS 1.2/1.3 only, redirects port 80 to 443 and limits `/auth/token` to 5 requests per minute per IP (burst 20, then `429`).

## Install

Requires Docker with Compose.

```sh
git clone https://github.com/kmpoltorak/fastapi-mysql-nginx.git
cd fastapi-mysql-nginx
cp .env.example .env    # set every value, alphanumeric, e.g. openssl rand -hex 32
```

## Quick start

```sh
docker compose up -d --build
```

Open https://localhost/ for the Swagger UI and accept the self-signed
certificate. Call `/auth/token` with `API_CLIENT_ID` / `API_CLIENT_SECRET`, click
**Authorize** and paste the `access_token`.

## Configuration

| Variable | Purpose |
|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL root, used only by the `db` container |
| `DB_PASSWORD` | MySQL user `api`: data operations |
| `AUTH_DB_PASSWORD` | MySQL user `api_auth`: the API clients and application users tables |
| `JWT_SECRET` | token signing key, at least 32 characters |
| `API_CLIENT_ID`, `API_CLIENT_SECRET` | first API client (default id `app`), created when the clients table is empty |
| `TZ` | timezone |

The MySQL users are created by [db/init/01-users.sh](db/init/01-users.sh) on
the first start with an empty volume. After changing `db/init/`, or on a volume
from an older version, recreate the database, which **deletes all data**:
`docker compose down -v && docker compose up -d --build`.

On first start Nginx generates a self-signed certificate into `nginx/certs/`.
To use your own, put `cert.pem` and `key.pem` (no passphrase) there and restart
the `proxy` service.

## API

Everything except `/health`, `/ready`, `/api` and `/auth/token` needs a client
Bearer token. The full schema is in the Swagger UI at `/`.

| Area | Endpoints |
|---|---|
| Health | `GET /health` (process only, for the container healthcheck), `GET /ready` (`SELECT 1` on both MySQL connections, `200` or `503`) |
| API clients | `POST /auth/token` → 15-minute JWT; `POST`, `GET /auth/clients`, `DELETE /auth/clients/{id}` |
| Databases | `GET /database/get`, `POST /database/create`, `DELETE /database/delete`, `POST /database/backup`, `POST /database/restore` |
| Tables | `GET /table/get/{db}`, `POST /table/create`, `PUT /table/rename`, `PUT /table/alter`, `DELETE /table/delete`, `GET /table/columns/{db}/{table}` |
| Rows | `POST /row/insert`, `GET /row/get/{db}/{table}?limit=&offset=` (limit 1–1000, default 100), `PUT /row/update`, `DELETE /row/delete` (by `row_id` on `key_column`, default `id`) |
| Users | `POST`, `GET /user`, `GET`, `PUT`, `DELETE /user/{id}`, `POST /user/login` |
| TOTP | `POST /user/{id}/totp/setup`, `POST /user/{id}/totp/enable`, `DELETE /user/{id}/totp` |

`PUT /table/alter` takes `action`: `add` or `modify` (need `params`), `drop`, or
`rename` (needs `new_column_name`). Backups include routines and events, with
binary columns as hex literals, so a dump restores byte for byte. A restore runs
as the `api` user; `DELIMITER` works, shell and file commands (`\!`, `source`)
return `400`.

`POST /user/login` with `{"username", "password", "totp"}`:

| Status | Meaning |
|---|---|
| `200` | correct; returns `id`, `username`, `email`, `totp_enabled`, `locked`, and the application starts its own session |
| `401 TOTP code required` | password correct, send again with `totp` |
| `401 Bad credentials` | wrong username, password or code |
| `423` | locked after 5 failed attempts; wait 15 minutes or change the password |

TOTP setup: `setup` returns a secret and an `otpauth://` URI to show as a QR
code and saves nothing; `enable` with `{"secret", "code"}` turns it on once the
authenticator produces a valid code.

Errors are `{"detail": "..."}` with `400` (rejected by MySQL), `401`, `404`,
`422` (invalid input, e.g. an identifier with forbidden characters), `423`,
`429` or `500`.

## Limitations

- Tokens are not checked against the database: a deleted client keeps access until its token expires (up to 15 minutes).
- `/database/restore` runs any SQL the `api` user may run, including on other databases it manages.
- Account lockout is per user, not per IP: all users arrive through the application's IP.
- The default certificate is self-signed.
- `/health` ignores MySQL by design; monitor `/ready` for database outages.

## Development

```sh
pip install -r app/requirements.txt flake8 pytest httpx
flake8 app
cd app && python -m pytest tests/test_app.py         # unit tests, database mocked

docker compose up -d --build --wait                  # integration tests, whole stack over HTTPS
set -a; . ./.env; set +a
cd app && INTEGRATION_URL=https://localhost python -m pytest tests/test_integration.py
```

Unit tests mock the database. Integration tests call the running stack through
Nginx with real MySQL. CI runs flake8 and the unit tests, then starts the stack
with generated secrets and runs the integration tests.

Built with an AI coding assistant. I wrote the spec and reviewed every change.

## License

MIT, see [LICENSE](LICENSE).
