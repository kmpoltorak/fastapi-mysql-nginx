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
    ApiKeyCreate,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    TotpCodeRequest,
    TotpEnableRequest,
    UserCreate,
    UserUpdate
)

Identifier = Annotated[str, Path(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
CurrentUser = Annotated[str, Depends(auth.get_current_user)]
SessionUser = Annotated[str, Depends(auth.get_session_user)]
Protected = [Depends(auth.get_current_user)]
SessionProtected = [Depends(auth.get_session_user)]

# Request tags
tags_metadata = [
    {
        "name": "API",
        "description": "General API endpoints including health and version."
    },
    {
        "name": "Auth",
        "description": """People: log in with `/login` (+ TOTP if enabled), click
        **Authorize** and paste the `access_token`; renew it with `/auth/refresh`.
        Scripts: create an API key and use it the same way (Bearer)."""
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
        "description": "Endpoints for API user management: create, update, delete, and fetch users."
    }
]

__version__ = "2.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the first admin user from env when the users table is empty."""
    if not query("SELECT COUNT(*) FROM api_auth.users", auth=True)[0]:
        query("INSERT INTO api_auth.users (username, email, password_hash) VALUES (%s, %s, %s)",
              params=(os.getenv("ADMIN_USERNAME", "admin"), "",
                      auth.hash_password(os.environ["ADMIN_PASSWORD"])),
              auth=True)
        logging.info("Created initial admin user")
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

# ------------------- AUTH ENDPOINTS -------------------


def issue_tokens(user_id: int, username: str) -> TokenResponse:
    """New short-lived access token + refresh token (stored as hash, single use)."""
    refresh_token = auth.new_token()
    query("DELETE FROM api_auth.refresh_tokens WHERE expires_at < NOW()", auth=True)
    query("INSERT INTO api_auth.refresh_tokens (token_hash, user_id, expires_at) "
          "VALUES (%s, %s, NOW() + INTERVAL %s HOUR)",
          params=(auth.token_hash(refresh_token), user_id, auth.REFRESH_HOURS), auth=True)
    return TokenResponse(access_token=auth.create_access_token(username),
                         refresh_token=refresh_token, expires_in=auth.ACCESS_MINUTES * 60)


@app.post("/login", tags=["Auth"], response_model=TokenResponse)
def login(request: LoginRequest):
    """Exchange username, password (and TOTP code if enabled) for access + refresh tokens."""
    rows = query("SELECT id, password_hash, totp_secret, totp_last_step FROM api_auth.users "
                 "WHERE username=%s", params=(request.username,), auth=True)
    user_id, password_hash, totp_secret, last_step = \
        rows[0] if rows else (None, auth.DUMMY_HASH, None, None)
    ok = auth.verify_password(request.password, password_hash) and bool(rows)
    if ok and totp_secret:
        step = auth.totp_step(totp_secret, request.totp, last_step)
        ok = step is not None
        if ok:
            query("UPDATE api_auth.users SET totp_last_step=%s WHERE id=%s",
                  params=(step, user_id), auth=True)
    if not ok:
        logging.warning("Failed login for user %r", request.username)
        raise HTTPException(status_code=401, detail="Bad credentials")
    return issue_tokens(user_id, request.username)


@app.post("/auth/refresh", tags=["Auth"], response_model=TokenResponse)
def refresh(request: RefreshRequest):
    """Get a new access token without password/TOTP. The refresh token is rotated:
    the used one stops working and a new one is returned."""
    hashed = auth.token_hash(request.refresh_token)
    rows = query("SELECT u.id, u.username FROM api_auth.refresh_tokens t "
                 "JOIN api_auth.users u ON u.id = t.user_id "
                 "WHERE t.token_hash=%s AND t.expires_at > NOW()", params=(hashed,), auth=True)
    query("DELETE FROM api_auth.refresh_tokens WHERE token_hash=%s", params=(hashed,), auth=True)
    if not rows:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return issue_tokens(*rows[0])


@app.post("/auth/logout", tags=["Auth"], response_model=APIResponse)
def logout(request: RefreshRequest):
    """Revoke the refresh token (the access token expires on its own within minutes)."""
    query("DELETE FROM api_auth.refresh_tokens WHERE token_hash=%s",
          params=(auth.token_hash(request.refresh_token),), auth=True)
    return APIResponse(code=200, message="Logged out")


@app.post("/auth/totp/setup", tags=["Auth"], response_model=APIResponse)
def totp_setup(username: SessionUser):
    """Generate a new TOTP secret. Scan `uri` as QR code, then confirm with /auth/totp/enable."""
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="MySQL API")
    return APIResponse(code=200, message="Scan the URI and confirm with a code",
                       data={"secret": secret, "uri": uri})


@app.post("/auth/totp/enable", tags=["Auth"], response_model=APIResponse)
def totp_enable(request: TotpEnableRequest, username: SessionUser):
    """Enable TOTP after proving the authenticator app generates valid codes."""
    step = auth.totp_step(request.secret, request.code)
    if step is None:
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    query("UPDATE api_auth.users SET totp_secret=%s, totp_last_step=%s WHERE username=%s",
          params=(request.secret, step, username), auth=True)
    return APIResponse(code=200, message="TOTP enabled, it is now required at login")


@app.delete("/auth/totp", tags=["Auth"], response_model=APIResponse)
def totp_disable(request: TotpCodeRequest, username: SessionUser):
    """Disable TOTP, confirmed with a current code from the authenticator app."""
    secret = query("SELECT totp_secret FROM api_auth.users WHERE username=%s",
                   params=(username,), auth=True)
    if not secret or not secret[0] or auth.totp_step(secret[0], request.code) is None:
        raise HTTPException(status_code=400, detail="TOTP not enabled or invalid code")
    query("UPDATE api_auth.users SET totp_secret=NULL, totp_last_step=NULL WHERE username=%s",
          params=(username,), auth=True)
    return APIResponse(code=200, message="TOTP disabled")


@app.post("/auth/api-keys", tags=["Auth"], response_model=APIResponse)
def create_api_key(request: ApiKeyCreate, username: SessionUser):
    """Create an API key for scripts (no TOTP needed). The key is shown only once."""
    key = auth.new_token(auth.API_KEY_PREFIX)
    query("INSERT INTO api_auth.api_keys (user_id, name, key_hash) "
          "SELECT id, %s, %s FROM api_auth.users WHERE username=%s",
          params=(request.name, auth.token_hash(key), username), auth=True)
    return APIResponse(code=200, message="Store the key now, it won't be shown again",
                       data={"name": request.name, "key": key})


@app.get("/auth/api-keys", tags=["Auth"], response_model=APIResponse)
def list_api_keys(username: SessionUser):
    """List your API keys (without the keys themselves)."""
    rows = query("SELECT k.id, k.name, k.created_at FROM api_auth.api_keys k "
                 "JOIN api_auth.users u ON u.id = k.user_id WHERE u.username=%s ORDER BY k.id",
                 params=(username,), auth=True)
    return APIResponse(code=200, message="API keys",
                       data=[dict(zip(("id", "name", "created_at"), row)) for row in rows])


@app.delete("/auth/api-keys/{key_id}", tags=["Auth"], response_model=APIResponse)
def delete_api_key(key_id: int, username: SessionUser):
    """Revoke one of your API keys."""
    owned = query("SELECT k.id FROM api_auth.api_keys k JOIN api_auth.users u "
                  "ON u.id = k.user_id WHERE k.id=%s AND u.username=%s",
                  params=(key_id, username), auth=True)
    if not owned:
        raise HTTPException(status_code=404, detail="API key not found")
    query("DELETE FROM api_auth.api_keys WHERE id=%s", params=(key_id,), auth=True)
    return APIResponse(code=200, message="API key revoked")

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

# ------------------- USER MANAGEMENT ENDPOINTS -------------------


USER_COLUMNS = "id, username, email, totp_secret IS NOT NULL"


def user_dict(row) -> dict:
    return dict(zip(("id", "username", "email", "totp_enabled"), row[:3] + (bool(row[3]),)))


def fetch_user(user_id: int) -> dict:
    rows = query(f"SELECT {USER_COLUMNS} FROM api_auth.users WHERE id=%s",
                 params=(user_id,), auth=True)
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    return user_dict(rows[0])


@app.get("/user",
         tags=["User"],
         response_model=APIResponse,
         summary="List users",
         dependencies=SessionProtected
         )
def list_users():
    """List all API users."""
    rows = query(f"SELECT {USER_COLUMNS} FROM api_auth.users ORDER BY id", auth=True)
    return APIResponse(code=200, message="Users fetched", data=[user_dict(r) for r in rows])


@app.post("/user",
          tags=["User"],
          response_model=APIResponse,
          summary="Create a new user",
          description="Create a new API user. Password is stored as a scrypt hash.",
          dependencies=SessionProtected
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
         dependencies=SessionProtected
         )
def get_user(user_id: int):
    """Get user by ID."""
    return APIResponse(code=200, message="User fetched", data=fetch_user(user_id))


@app.put("/user/{user_id}",
         tags=["User"],
         response_model=APIResponse,
         summary="Update user by ID",
         description="Update user email and/or password by their unique ID.",
         dependencies=SessionProtected
         )
def update_user(user_id: int, user: UserUpdate):
    """Update user by ID."""
    fetch_user(user_id)
    if user.email is not None:
        query("UPDATE api_auth.users SET email=%s WHERE id=%s",
              params=(user.email, user_id), auth=True)
    if user.password is not None:
        query("UPDATE api_auth.users SET password_hash=%s WHERE id=%s",
              params=(auth.hash_password(user.password), user_id), auth=True)
        # log out everywhere: existing refresh tokens stop working
        query("DELETE FROM api_auth.refresh_tokens WHERE user_id=%s", params=(user_id,), auth=True)
    return APIResponse(code=200, message="User updated", data=fetch_user(user_id))


@app.delete("/user/{user_id}",
            tags=["User"],
            response_model=APIResponse,
            summary="Delete user by ID",
            description="Delete a user by their unique ID.",
            dependencies=SessionProtected
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
