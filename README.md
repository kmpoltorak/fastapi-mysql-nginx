# FastAPI + MySQL + Nginx Microservice

This project is a simple microservice stack for development and learning purposes. It provides a REST API (FastAPI) for MySQL database management, served behind Nginx. All services are containerized with Docker Compose.

## Features

- Database management: create, list, delete, backup, restore
- Table management: create, list, delete, rename, alter columns (add/modify/drop/rename), describe columns
- Row management: insert, get (paginated), update, delete (by `id` or any `key_column`)
- API user management: create, list, get, update, delete (stored in MySQL, scrypt password hashes)
- Login with username + password (+ optional TOTP 2FA): 15 min access token + 8 h rotated refresh token, logout
- API keys for scripts/automation (hashed in DB, revocable, can't manage accounts)
- HTTPS in Nginx (self-signed by default), HTTP -> HTTPS redirect, login rate limit
- Least-privilege MySQL users instead of `root`
- Linting (flake8), unit and integration tests (pytest), run in GitHub Actions CI

## Requirements

- Docker
- Docker Compose

## Configuration

Copy `.env.example` to `.env` and set every value; the stack refuses to start with missing secrets. Use alphanumeric values, e.g. `openssl rand -hex 32`.

| Variable | Purpose |
|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL root (used only by the `db` container) |
| `DB_PASSWORD` | MySQL user `api` – data operations |
| `AUTH_DB_PASSWORD` | MySQL user `api_auth` – API users table only |
| `JWT_SECRET` | Token signing key (at least 32 characters) |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | First API user, created when the users table is empty |
| `TZ` | Timezone |

## Security Model

- **MySQL users** (created by [db/init/01-users.sh](db/init/01-users.sh) on first start with an empty volume):
  - `api` – may create/modify any database, but has no access to `mysql`, `sys` and `api_auth` (MySQL `partial_revokes`), cannot create users or grant privileges.
  - `api_auth` – only `SELECT/INSERT/UPDATE/DELETE` on `api_auth.users`.
  - So even arbitrary SQL sent to `/database/restore` cannot read password hashes or create an admin.
- **Access tokens** – JWT (HS256) valid for 15 minutes, not checked against the DB (fast); a deleted user keeps access until it expires.
- **Refresh tokens** – random, stored only as SHA-256, valid 8 hours, single use (each refresh returns a new one). Logout, password change and user deletion revoke them.
- **API keys** – `mk_...`, stored only as SHA-256, shown once. They work for database/table/row endpoints but get `403` on user, API key and TOTP management, so a leaked key can't take over the account.
- **TOTP** – each code works only once (the last used 30 s time step is stored).
- **Nginx** – TLS 1.2/1.3, port 80 redirects to 443, `/login` limited to 5 requests/min per IP (burst 20, then HTTP 429).

After changing `db/init/` or on an existing volume from a previous version, recreate the database (**deletes all data**):

```
docker compose down -v && docker compose up -d --build
```

## Deployment

Build and start all services:

```
docker compose up -d --build
```

Open https://localhost/ (accept the self-signed certificate warning).

## HTTPS Certificate

On first start Nginx generates a self-signed certificate into `nginx/certs/` (git-ignored). To use your own, put `cert.pem` and `key.pem` (without passphrase) there and restart the `proxy` service.

## Example: Running Containers

After starting the services, check running containers:
```sh
$ docker ps
CONTAINER ID   IMAGE                       COMMAND                  ...
...           fastapi-mysql-nginx_proxy   ...
...           fastapi-mysql-nginx_app     ...
...           mysql:8.4                   ...
```

## API Usage

You can use the FastAPI Swagger UI (available at `/`) or tools like curl/Postman. All endpoints except `/health`, `/api` and `/login` require a Bearer token.

### Login (people)

```
curl -k -X POST https://localhost/login -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "<ADMIN_PASSWORD>"}'
# {"access_token": "eyJ...", "refresh_token": "...", "token_type": "bearer", "expires_in": 900}

curl -k https://localhost/database/get -H 'Authorization: Bearer eyJ...'
```

In Swagger: call `/login`, click **Authorize** and paste the `access_token`.

Before the access token expires, get a new pair without password/TOTP:

```
POST /auth/refresh   {"refresh_token": "..."}   # the old refresh token stops working
POST /auth/logout    {"refresh_token": "..."}
```

### API keys (scripts, cron, CI)

TOTP needs a phone, so scripts use API keys instead. Log in as a person, then:

```
POST /auth/api-keys  {"name": "nightly-backup"}   # returns "key": "mk_..." – shown only once
GET  /auth/api-keys                               # list (names, no keys)
DELETE /auth/api-keys/{id}                        # revoke
```

Use it like a token: `Authorization: Bearer mk_...`.

### TOTP (two-factor authentication)

1. `POST /auth/totp/setup` – returns `secret` and an `otpauth://` `uri` (turn it into a QR code, e.g. `qrencode -t ansiutf8 '<uri>'`, or type the secret into Google Authenticator, Aegis, 1Password...).
2. `POST /auth/totp/enable` with `{"secret": "...", "code": "123456"}` – confirms the app works and turns TOTP on.
3. From now on `/login` requires `"totp": "123456"` (once per session, `/auth/refresh` doesn't need it). Each code can be used only once.
4. `DELETE /auth/totp` with `{"code": "123456"}` turns it off.

Lost the authenticator? Reset it as MySQL root: `UPDATE api_auth.users SET totp_secret = NULL, totp_last_step = NULL WHERE username = '...';`

### Errors

Errors use HTTP status codes with `{"detail": "..."}`: `400` statement rejected by MySQL (bad SQL, missing table, duplicate...), `401` missing/invalid token or bad credentials, `403` API key used for account management, `404` user not found, `422` invalid input (e.g. identifier with forbidden characters), `429` too many login attempts, `500` server/connection error.

### Example: Create Table

Request:
```
POST /table/create
{
  "database_name": "test",
  "table_name": "person",
  "columns": [
    { "name": "id", "params": "int not null auto_increment primary key" },
    { "name": "name", "params": "varchar(255)" },
    { "name": "surname", "params": "varchar(255) not null" }
  ]
}
```

Result in MySQL:
```
mysql> show columns from person;
+---------+--------------+------+-----+---------+----------------+
| Field   | Type         | Null | Key | Default | Extra          |
+---------+--------------+------+-----+---------+----------------+
| id      | int          | NO   | PRI | NULL    | auto_increment |
| name    | varchar(255) | YES  |     | NULL    |                |
| surname | varchar(255) | NO   |     | NULL    |                |
+---------+--------------+------+-----+---------+----------------+
```

### Alter Table

```
PUT /table/alter
{ "database_name": "test", "table_name": "person", "action": "add", "column_name": "age", "params": "INT DEFAULT 0" }
```

`action`: `add` / `modify` (need `params`), `drop`, `rename` (needs `new_column_name`).

### Rows

```
GET /row/get/test/person?limit=100&offset=0          # limit 1–1000, default 100

PUT /row/update
{ "database_name": "test", "table_name": "person", "row_id": 1, "values": {"name": "Ann"} }
# optional "key_column": "person_id" (default "id"), same for DELETE /row/delete
```

### Database Backup & Restore

**Backup:**
```
POST /database/backup
{
  "database_name": "testdb"
}
```
Response: SQL dump string in `data` field.

**Restore:**
```
POST /database/restore
{
  "database_name": "testdb",
  "sql_dump": "CREATE TABLE ...; INSERT INTO ...; ..."
}
```

**Note:** The SQL dump must be valid MySQL SQL. The operation is executed directly on the database.

## Linting & Tests

Unit tests mock the database:

```
pip install -r app/requirements.txt flake8 pytest httpx
flake8 app
cd app && python -m pytest tests/test_app.py
```

Integration tests run against the whole running stack over HTTPS:

```
docker compose up -d --build --wait
set -a; . ./.env; set +a
cd app && INTEGRATION_URL=https://localhost python -m pytest tests/test_integration.py
```
