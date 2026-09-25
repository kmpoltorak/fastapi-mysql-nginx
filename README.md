# FastAPI + MySQL + Nginx Microservice

This project is a simple microservice stack for development and learning purposes. It provides a REST API (FastAPI) for MySQL database management, served behind Nginx. All services are containerized with Docker Compose.

The API is a middle layer between an application and the database:

```
User ──(password + TOTP)──▶ Application ──(client JWT)──▶ Nginx (HTTPS) ──▶ API ──▶ MySQL
                                 │                                           │
                                 └──────── POST /user/login ─────────────────┘
                                          (API verifies password + TOTP)
```

- **API clients** (the application, scripts) authenticate to the API with `client_id` + `client_secret` → JWT.
- **Application users** are stored and verified by the API (`/user`, `/user/login` with optional TOTP); the application keeps its own user session.

## Features

- Database management: create, list, delete, backup, restore
- Table management: create, list, delete, rename, alter columns (add/modify/drop/rename), describe columns
- Row management: insert, get (paginated), update, delete (by `id` or any `key_column`)
- API clients: OAuth2 client credentials → 15 min JWT, create/list/delete clients
- Application users: create, list, get, update, delete (scrypt password hashes), login verification with optional TOTP 2FA, account lockout after failed attempts
- HTTPS in Nginx (self-signed by default), HTTP -> HTTPS redirect, token endpoint rate limit
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
| `AUTH_DB_PASSWORD` | MySQL user `api_auth` – API clients and application users tables only |
| `JWT_SECRET` | Token signing key (at least 32 characters) |
| `API_CLIENT_ID`, `API_CLIENT_SECRET` | First API client (default id `app`), created when the clients table is empty |
| `TZ` | Timezone |

## Security Model

- **MySQL users** (created by [db/init/01-users.sh](db/init/01-users.sh) on first start with an empty volume):
  - `api` – may create/modify any database, but has no access to `mysql`, `sys` and `api_auth` (MySQL `partial_revokes`), cannot create users or grant privileges.
  - `api_auth` – only `SELECT/INSERT/UPDATE/DELETE` on `api_auth` tables (`clients`, `users`), no DDL.
  - So even arbitrary SQL sent to `/database/restore` cannot read password hashes or create a client.
- **Passwords and client secrets** – hashed with scrypt + random salt (one-way, not encrypted), never returned by the API. Client secrets are shown only once, on creation.
- **Access tokens** – JWT (HS256) valid for 15 minutes, not checked against the DB (fast); a deleted client keeps access until it expires. Clients simply request a new token.
- **TOTP** – each code works only once (the last used 30 s time step is stored).
- **Account lockout** – 5 wrong passwords/TOTP codes lock the user for 15 minutes (HTTP 423); a password change unlocks. Not done by IP in Nginx, because all users come through the application's IP.
- **Nginx** – TLS 1.2/1.3, port 80 redirects to 443, `/auth/token` limited to 5 requests/min per IP (burst 20, then HTTP 429).

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

You can use the FastAPI Swagger UI (available at `/`) or tools like curl/Postman. All endpoints except `/health`, `/api` and `/auth/token` require a client Bearer token.

### API client token

```
curl -k -X POST https://localhost/auth/token -H 'Content-Type: application/json' \
  -d '{"client_id": "app", "client_secret": "<API_CLIENT_SECRET>"}'
# {"access_token": "eyJ...", "token_type": "bearer", "expires_in": 900}

curl -k https://localhost/database/get -H 'Authorization: Bearer eyJ...'
```

In Swagger: call `/auth/token`, click **Authorize** and paste the `access_token`. When it expires, request a new one.

More clients (e.g. one per application or script, so each can be revoked separately):

```
POST   /auth/clients  {"client_id": "nightly-backup"}   # returns client_secret – shown only once
GET    /auth/clients
DELETE /auth/clients/nightly-backup
```

### Application users

```
POST /user        {"username": "john", "email": "john@example.com", "password": "..."}
POST /user/login  {"username": "john", "password": "...", "totp": "123456"}
```

`/user/login` returns the user (`id`, `username`, `email`, `totp_enabled`, `locked`) on success; the application then starts its own session. Responses:

| Status | Meaning | What the application does |
|---|---|---|
| `200` | password (and TOTP) correct | log the user in |
| `401` `TOTP code required` | password correct, TOTP enabled, `totp` missing | ask for the code, send again with `totp` |
| `401` `Bad credentials` | wrong username, password or TOTP code | show an error |
| `423` | account locked after 5 failed attempts | ask to wait 15 minutes (or reset password) |

### TOTP (two-factor authentication for users)

The user scans a QR code with an authenticator app (Google Authenticator, Aegis, 1Password...). The app and the API share a secret and both compute the same 6-digit code from it and the current time (every 30 s), so no connection between them is needed.

1. `POST /user/{id}/totp/setup` – returns `secret` and an `otpauth://` `uri`; the application shows the `uri` as a QR code (for testing: `qrencode -t ansiutf8 '<uri>'`). Nothing is saved yet.
2. `POST /user/{id}/totp/enable` with `{"secret": "...", "code": "123456"}` – proves the authenticator works and turns TOTP on.
3. From now on `/user/login` requires `totp`. Each code can be used only once.
4. `DELETE /user/{id}/totp` – turns it off (e.g. lost phone); the application decides who may do it.

### Errors

Errors use HTTP status codes with `{"detail": "..."}`: `400` statement rejected by MySQL (bad SQL, missing table, duplicate...), `401` missing/invalid token or bad credentials, `404` user/client not found, `423` user locked, `422` invalid input (e.g. identifier with forbidden characters), `429` too many token requests, `500` server/connection error.

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
