import logging
import subprocess
import os
from contextlib import asynccontextmanager
from typing import Annotated

import mysql.connector
import pyotp
from fastapi import FastAPI, Depends, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

import auth
from utils import query
from model import (
    APIResponse,
    DatabaseRequest,
    TableAlterRequest,
    TableCreateRequest,
    TableRenameRequest,
    TableRequest,
    RowInsertRequest,
    RowUpdateRequest,
    RowDeleteRequest,
    DatabaseBackupRequest,
    DatabaseRestoreRequest,
    ClientCreate,
    TokenRequest,
    TokenResponse,
    TotpEnableRequest,
    UserLoginRequest,
    UserCreate,
    UserUpdate
)

Identifier = Annotated[str, Path(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
CurrentClient = Annotated[str, Depends(auth.get_current_client)]
Protected = [Depends(auth.get_current_client)]

# Request tags
tags_metadata = [
    {
        "name": "API",
        "description": "General API endpoints including health and version."
    },
    {
        "name": "Auth",
        "description": """API clients (applications, scripts) get a JWT from `/auth/token`
        with `client_id` + `client_secret`, then click **Authorize** and paste it."""
    },
    {
        "name": "Database",
        "description": """Endpoints for database management:
        create, delete, backup, restore, and list databases."""
    },
    {
        "name": "Table",
        "description": """Endpoints for table management:
        create, delete, rename, alter columns, list tables, and describe columns."""
    },
    {
        "name": "Row",
        "description": "Endpoints for row operations: insert, get (paginated), update, delete."
    },
    {
        "name": "User",
        "description": """Users of the application: CRUD, password + TOTP verification
        with `/user/login` (the application keeps its own session), TOTP setup."""
    }
]

__version__ = "2.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the first API client from env when the clients table is empty."""
    if not query("SELECT COUNT(*) FROM api_auth.clients", auth=True)[0]:
        query("INSERT INTO api_auth.clients (client_id, secret_hash) VALUES (%s, %s)",
              params=(os.getenv("API_CLIENT_ID", "app"),
                      auth.hash_password(os.environ["API_CLIENT_SECRET"])),
              auth=True)
        logging.info("Created initial API client")
    yield


app = FastAPI(
    title="MySQL API",
    version=__version__,
    openapi_tags=tags_metadata,
    redoc_url=None,
    docs_url="/",
    lifespan=lifespan,
)

origins = [
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware)

# Configure logging
logging.basicConfig(filename="debug.log",
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    level=logging.INFO
                    )


@app.exception_handler(mysql.connector.Error)
async def mysql_error_handler(request: Request, exc: mysql.connector.Error):
    """Statement rejected by the server (bad SQL, missing table, duplicate...) -> 400.

    No SQLSTATE (connector/pool errors), connection (08) or app login (28) errors -> 500.
    """
    status = 400 if exc.sqlstate and not exc.sqlstate.startswith(("08", "28")) else 500
    return JSONResponse(status_code=status, content={"detail": str(exc)})

# ------------------- API ENDPOINTS -------------------


@app.get("/health",
         tags=["API"]
         )
async def health():
    return {"status": "ok"}


@app.get("/api",
         tags=["API"],
         name="",
         response_model=APIResponse
         )
async def api():
    """Return API version

    Returns:
        APIResponse: message with API version
    """
    return APIResponse(code=200, message=f"MySQL API version {__version__}")

# ------------------- AUTH ENDPOINTS (API CLIENTS) -------------------


@app.post("/auth/token", tags=["Auth"], response_model=TokenResponse)
def token(request: TokenRequest):
    """OAuth2 client credentials: exchange client_id + client_secret for a JWT access token."""
    rows = query("SELECT secret_hash FROM api_auth.clients WHERE client_id=%s",
                 params=(request.client_id,), auth=True)
    if not (auth.verify_password(request.client_secret, rows[0] if rows else auth.DUMMY_HASH)
            and rows):
        logging.warning("Failed token request for client %r", request.client_id)
        raise HTTPException(status_code=401, detail="Bad client credentials")
    return TokenResponse(access_token=auth.create_access_token(request.client_id),
                         expires_in=auth.ACCESS_MINUTES * 60)


@app.post("/auth/clients", tags=["Auth"], response_model=APIResponse, dependencies=Protected)
def create_client(request: ClientCreate):
    """Register a new API client. The secret is shown only once."""
    secret = auth.new_secret()
    query("INSERT INTO api_auth.clients (client_id, secret_hash) VALUES (%s, %s)",
          params=(request.client_id, auth.hash_password(secret)), auth=True)
    return APIResponse(code=200, message="Store the secret now, it won't be shown again",
                       data={"client_id": request.client_id, "client_secret": secret})


@app.get("/auth/clients", tags=["Auth"], response_model=APIResponse, dependencies=Protected)
def list_clients():
    """List API clients (without secrets)."""
    rows = query("SELECT client_id, created_at FROM api_auth.clients ORDER BY id", auth=True)
    return APIResponse(code=200, message="API clients",
                       data=[dict(zip(("client_id", "created_at"), row)) for row in rows])


@app.delete("/auth/clients/{client_id}", tags=["Auth"], response_model=APIResponse)
def delete_client(client_id: str, current: CurrentClient):
    """Revoke an API client (its current tokens expire within ACCESS_MINUTES)."""
    if client_id == current:
        raise HTTPException(status_code=400, detail="Can't delete the client you are using")
    if not query("SELECT id FROM api_auth.clients WHERE client_id=%s",
                 params=(client_id,), auth=True):
        raise HTTPException(status_code=404, detail="Client not found")
    query("DELETE FROM api_auth.clients WHERE client_id=%s", params=(client_id,), auth=True)
    return APIResponse(code=200, message="Client deleted")

# ------------------- DATABASE ENDPOINTS -------------------


@app.get("/database/get",
         tags=["Database"],
         name="",
         response_model=APIResponse,
         dependencies=Protected
         )
def get_db():
    """Return existing databases list

    Returns:
        APIResponse: code and message about statement status
    """
    return APIResponse(code=200, message="Existing databases", data=query("SHOW DATABASES"))


@app.post("/database/create", tags=["Database"], name="",
          response_model=APIResponse, dependencies=Protected)
def create_db(request: DatabaseRequest):
    """Create new database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        APIResponse: code and message about statement status
    """
    query(f"CREATE DATABASE {request.database_name}")
    return APIResponse(code=200, message=f"Database {request.database_name} has been created")


@app.delete("/database/delete",
            tags=["Database"],
            name="",
            response_model=APIResponse,
            dependencies=Protected
            )
def delete_db(request: DatabaseRequest):
    """Delete existing database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        APIResponse: code and message about statement status
    """
    query(f"DROP DATABASE {request.database_name}")
    return APIResponse(code=200, message=f"Database {request.database_name} has been deleted")

# ------------------- TABLE ENDPOINTS -------------------


@app.get("/table/get/{database_name}",
         tags=["Table"],
         name="",
         response_model=APIResponse,
         dependencies=Protected
         )
def get_table(database_name: Identifier):
    """Show existing tables in provided database

    Args:
        database_name (str): database name provided as request query parameter

    Returns:
        APIResponse: code and message about statement status
    """
    return APIResponse(code=200, message=f'Existing tables in database {database_name}',
                       data=query("SHOW TABLES", database_name))


@app.post("/table/create",
          tags=["Table"],
          name="",
          response_model=APIResponse,
          dependencies=Protected
          )
def create_table(request: TableCreateRequest):
    """Create table with columns that have constraints

    Args:
        request (TableRequest):
            database_name (str): database name
            table_name (str): table name

    Returns:
        APIResponse: code and message about statement status
    """
    columns = ",".join([f"{column.name} {column.params}" for column in request.columns])
    query(f"CREATE TABLE {request.table_name} ({columns})", request.database_name)
    return APIResponse(code=200, message=f'Table {request.table_name} in database '
                                         f'{request.database_name} has been created')


@app.put("/table/rename",
         tags=["Table"],
         name="",
         response_model=APIResponse,
         dependencies=Protected
         )
def rename_table(request: TableRenameRequest):
    """Rename existing table name to new one

    Args:
        request (TableRenameRequest):
            database_name (str): database name
            old_table_name (str): existing table name
            new_table_name (str): table name after change

    Returns:
        APIResponse: Code and message about statement status
    """
    query(f"RENAME TABLE {request.old_table_name} TO {request.new_table_name}",
          request.database_name)
    return APIResponse(
        code=200,
        message=f"Table {request.old_table_name} has been renamed to "
                f"{request.new_table_name} in database {request.database_name}"
    )


@app.put("/table/alter",
         tags=["Table"],
         response_model=APIResponse,
         dependencies=Protected
         )
def alter_table(request: TableAlterRequest):
    """Add, modify, drop or rename a column (ALTER TABLE)"""
    column = request.column_name
    clause = {
        "add": f"ADD COLUMN {column} {request.params}",
        "modify": f"MODIFY COLUMN {column} {request.params}",
        "drop": f"DROP COLUMN {column}",
        "rename": f"RENAME COLUMN {column} TO {request.new_column_name}",
    }[request.action]
    query(f"ALTER TABLE {request.table_name} {clause}", request.database_name)
    return APIResponse(code=200, message=f"Table {request.table_name} altered: {clause}")


@app.delete("/table/delete",
            tags=["Table"],
            name="",
            response_model=APIResponse,
            dependencies=Protected
            )
def delete_table(request: TableRequest):
    """Delete table if exist

    Args:
        request (TableRequest):
            database_name (str): database name
            table_name (str): table name

    Returns:
        APIResponse: Code and message about statement status
    """
    query(f"DROP TABLE {request.table_name}", request.database_name)
    return APIResponse(code=200, message=f'Table {request.table_name} has been deleted '
                                         f'from database {request.database_name}')


@app.get("/table/columns/{database_name}/{table_name}",
         tags=["Table"],
         response_model=APIResponse,
         dependencies=Protected
         )
def get_table_columns(database_name: Identifier, table_name: Identifier):
    """Get columns for a given table (DESCRIBE table)."""
    return APIResponse(code=200, message=f'Columns for table {table_name}',
                       data=query(f"DESCRIBE {table_name}", database_name))

# ------------------- ROW CRUD ENDPOINTS -------------------


@app.post("/row/insert",
          tags=["Row"],
          response_model=APIResponse,
          dependencies=Protected
          )
def insert_row(request: RowInsertRequest):
    """Insert a new record into a table"""
    columns = ', '.join(request.values.keys())
    placeholders = ', '.join(['%s'] * len(request.values))
    query(f"INSERT INTO {request.table_name} ({columns}) VALUES ({placeholders})",
          request.database_name, params=tuple(request.values.values()))
    return APIResponse(code=200, message='Row inserted')


@app.get("/row/get/{database_name}/{table_name}",
         tags=["Row"],
         response_model=APIResponse,
         dependencies=Protected
         )
def get_rows(database_name: Identifier, table_name: Identifier,
             limit: Annotated[int, Query(ge=1, le=1000)] = 100,
             offset: Annotated[int, Query(ge=0)] = 0):
    """Get records from a table, paginated with limit/offset"""
    result = query(f"SELECT * FROM {table_name} LIMIT %s OFFSET %s", database_name,
                   params=(limit, offset))
    return APIResponse(code=200, message='Rows fetched', data=result)


@app.put("/row/update",
         tags=["Row"],
         response_model=APIResponse,
         dependencies=Protected
         )
def update_row(request: RowUpdateRequest):
    """Update a record in a table by its key column (default: id)"""
    set_clause = ', '.join([f"{k}=%s" for k in request.values.keys()])
    query(f"UPDATE {request.table_name} SET {set_clause} WHERE {request.key_column}=%s",
          request.database_name, params=tuple(request.values.values()) + (request.row_id,))
    return APIResponse(code=200, message='Row updated')


@app.delete("/row/delete",
            tags=["Row"],
            response_model=APIResponse,
            dependencies=Protected
            )
def delete_row(request: RowDeleteRequest):
    """Delete a record from a table by its key column (default: id)"""
    query(f"DELETE FROM {request.table_name} WHERE {request.key_column}=%s",
          request.database_name, params=(request.row_id,))
    return APIResponse(code=200, message='Row deleted')

# ------------------- APPLICATION USER ENDPOINTS -------------------


USER_COLUMNS = "id, username, email, totp_secret IS NOT NULL, locked_until > NOW()"


def user_dict(row) -> dict:
    return dict(zip(("id", "username", "email", "totp_enabled", "locked"),
                    row[:3] + (bool(row[3]), bool(row[4]))))


def fetch_user(user_id: int) -> dict:
    rows = query(f"SELECT {USER_COLUMNS} FROM api_auth.users WHERE id=%s",
                 params=(user_id,), auth=True)
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return user_dict(rows[0])


@app.post("/user/login",
          tags=["User"],
          response_model=APIResponse,
          summary="Verify user login",
          dependencies=Protected,
          responses={401: {"description": "Bad credentials or TOTP code required"},
                     423: {"description": "Account locked after too many failed attempts"}}
          )
def user_login(request: UserLoginRequest):
    """Check password (and TOTP if enabled) of an application user.

    Returns the user on success; the application then starts its own session.
    If the password is right but TOTP is enabled and `totp` is missing, returns 401
    "TOTP code required" so the application can ask for it and retry.
    After MAX_FAILED_LOGINS wrong attempts the account is locked for LOCK_MINUTES.
    """
    rows = query("SELECT id, password_hash, totp_secret, totp_last_step, "
                 "locked_until > NOW() FROM api_auth.users WHERE username=%s",
                 params=(request.username,), auth=True)
    user_id, password_hash, totp_secret, last_step, locked = \
        rows[0] if rows else (None, auth.DUMMY_HASH, None, None, False)
    if locked:
        raise HTTPException(status_code=423, detail="Account locked, try again later")
    password_ok = auth.verify_password(request.password, password_hash) and bool(rows)
    if password_ok and totp_secret and not request.totp:
        raise HTTPException(status_code=401, detail="TOTP code required")
    step = auth.totp_step(totp_secret, request.totp, last_step) if totp_secret else None
    if not password_ok or (totp_secret and step is None):
        if rows:
            query("UPDATE api_auth.users SET failed_logins = failed_logins + 1, "
                  "locked_until = IF(failed_logins >= %s, NOW() + INTERVAL %s MINUTE, NULL), "
                  "failed_logins = IF(failed_logins >= %s, 0, failed_logins) WHERE id=%s",
                  params=(auth.MAX_FAILED_LOGINS, auth.LOCK_MINUTES, auth.MAX_FAILED_LOGINS,
                          user_id), auth=True)
        logging.warning("Failed login for user %r", request.username)
        raise HTTPException(status_code=401, detail="Bad credentials")
    query("UPDATE api_auth.users SET failed_logins=0, locked_until=NULL, "
          "totp_last_step=COALESCE(%s, totp_last_step) WHERE id=%s",
          params=(step, user_id), auth=True)
    return APIResponse(code=200, message="Login successful", data=fetch_user(user_id))


@app.post("/user/{user_id}/totp/setup",
          tags=["User"],
          response_model=APIResponse,
          summary="Generate TOTP secret",
          dependencies=Protected
          )
def user_totp_setup(user_id: int):
    """New TOTP secret for the user. Show `uri` as QR code, then confirm with .../totp/enable.
    Nothing is saved until confirmed."""
    user = fetch_user(user_id)
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="MySQL API")
    return APIResponse(code=200, message="Show the URI as QR code and confirm with a code",
                       data={"secret": secret, "uri": uri})


@app.post("/user/{user_id}/totp/enable",
          tags=["User"],
          response_model=APIResponse,
          summary="Enable TOTP",
          dependencies=Protected
          )
def user_totp_enable(user_id: int, request: TotpEnableRequest):
    """Enable TOTP after the user proves their authenticator app generates valid codes."""
    fetch_user(user_id)
    step = auth.totp_step(request.secret, request.code)
    if step is None:
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    query("UPDATE api_auth.users SET totp_secret=%s, totp_last_step=%s WHERE id=%s",
          params=(request.secret, step, user_id), auth=True)
    return APIResponse(code=200, message="TOTP enabled, it is now required at login")


@app.delete("/user/{user_id}/totp",
            tags=["User"],
            response_model=APIResponse,
            summary="Disable TOTP",
            dependencies=Protected
            )
def user_totp_disable(user_id: int):
    """Disable TOTP (e.g. lost phone). The application decides who may do this."""
    fetch_user(user_id)
    query("UPDATE api_auth.users SET totp_secret=NULL, totp_last_step=NULL WHERE id=%s",
          params=(user_id,), auth=True)
    return APIResponse(code=200, message="TOTP disabled")


@app.get("/user",
         tags=["User"],
         response_model=APIResponse,
         summary="List users",
         dependencies=Protected
         )
def list_users():
    """List all application users."""
    rows = query(f"SELECT {USER_COLUMNS} FROM api_auth.users ORDER BY id", auth=True)
    return APIResponse(code=200, message="Users fetched", data=[user_dict(r) for r in rows])


@app.post("/user",
          tags=["User"],
          response_model=APIResponse,
          summary="Create a new user",
          description="Create a new application user. Password is stored as a scrypt hash.",
          dependencies=Protected
          )
def create_user(user: UserCreate):
    """Create a new user."""
    query("INSERT INTO api_auth.users (username, email, password_hash) VALUES (%s, %s, %s)",
          params=(user.username, user.email, auth.hash_password(user.password)), auth=True)
    user_id = query("SELECT id FROM api_auth.users WHERE username=%s",
                    params=(user.username,), auth=True)[0]
    return APIResponse(code=200, message="User created", data=fetch_user(user_id))


@app.get("/user/{user_id}",
         tags=["User"],
         response_model=APIResponse,
         summary="Get user by ID",
         description="Fetch a user by their unique ID.",
         dependencies=Protected
         )
def get_user(user_id: int):
    """Get user by ID."""
    return APIResponse(code=200, message="User fetched", data=fetch_user(user_id))


@app.put("/user/{user_id}",
         tags=["User"],
         response_model=APIResponse,
         summary="Update user by ID",
         description="Update email and/or password. A password change also unlocks the account.",
         dependencies=Protected
         )
def update_user(user_id: int, user: UserUpdate):
    """Update user by ID."""
    fetch_user(user_id)
    if user.email is not None:
        query("UPDATE api_auth.users SET email=%s WHERE id=%s",
              params=(user.email, user_id), auth=True)
    if user.password is not None:
        query("UPDATE api_auth.users SET password_hash=%s, failed_logins=0, locked_until=NULL "
              "WHERE id=%s", params=(auth.hash_password(user.password), user_id), auth=True)
    return APIResponse(code=200, message="User updated", data=fetch_user(user_id))


@app.delete("/user/{user_id}",
            tags=["User"],
            response_model=APIResponse,
            summary="Delete user by ID",
            description="Delete a user by their unique ID.",
            dependencies=Protected
            )
def delete_user(user_id: int):
    """Delete user by ID."""
    fetch_user(user_id)
    query("DELETE FROM api_auth.users WHERE id=%s", params=(user_id,), auth=True)
    return APIResponse(code=200, message="User deleted")

# ------------------- DATABASE BACKUP AND RESTORE ENDPOINTS -------------------


def run_mysql_tool(tool: str, database_name: str, *args: str, stdin: str = None):
    """Run mysql/mysqldump as the `api` user; password is passed via env."""
    cmd = [
        tool,
        f"-h{os.getenv('MYSQL_HOST', 'db')}",
        "-uapi",
        "--ssl-verify-server-cert=OFF",
        *args,
        database_name
    ]
    env = {**os.environ, "MYSQL_PWD": os.environ["DB_PASSWORD"]}
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env)


@app.post("/database/backup",
          tags=["Database"],
          response_model=APIResponse,
          dependencies=Protected
          )
def backup_database(request: DatabaseBackupRequest):
    """Backup a database and return SQL dump as string."""
    # --no-tablespaces: tablespace info needs the global PROCESS privilege
    result = run_mysql_tool("mysqldump", request.database_name, "--no-tablespaces")
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"mysqldump error: {result.stderr}")
    return APIResponse(code=200, message="Backup successful", data=result.stdout)


@app.post("/database/restore",
          tags=["Database"],
          response_model=APIResponse,
          dependencies=Protected
          )
def restore_database(request: DatabaseRestoreRequest):
    """Restore a database from SQL dump string."""
    if not request.sql_dump.strip():
        raise HTTPException(status_code=400, detail="SQL dump is empty")
    result = run_mysql_tool("mysql", request.database_name, stdin=request.sql_dump)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"mysql error: {result.stderr}")
    return APIResponse(code=200, message="Restore successful")
