import logging
import subprocess
import os
from typing import Annotated

from fastapi import FastAPI, Depends, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import auth
from utils import SqlOperation
from model import (
    APIResponse,
    DatabaseRequest,
    TableCreateRequest,
    TableRenameRequest,
    TableRequest,
    RowInsertRequest,
    RowUpdateRequest,
    RowDeleteRequest,
    DatabaseBackupRequest,
    DatabaseRestoreRequest,
    UserCreate,
    UserUpdate
)

Identifier = Annotated[str, Path(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

# Request tags
tags_metadata = [
    {
        "name": "API",
        "description": "General API endpoints including health and version."
    },
    {
        "name": "Database",
        "description": """Endpoints for database management:
        create, delete, backup, restore, and list databases."""
    },
    {
        "name": "Table",
        "description": """Endpoints for table management:
        create, delete, rename, list tables, and row/column operations."""
    },
    {
        "name": "User",
        "description": "Endpoints for user management: create, update, delete, and fetch users."
    }
]

__version__ = "1.3.0"

# Initiate FastAPI with vault API key authentication by "AccessToken" in request header
app = FastAPI(
    title="MySQL API",
    version=__version__,
    openapi_tags=tags_metadata,
    redoc_url=None,
    docs_url="/",
)

origins = [
    "http://127.0.0.1",
    "http://localhost",
    "http://127.0.0.1:8080",
    "http://localhost:8080"
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

# ------------------- DATABASE ENDPOINTS -------------------


@app.get("/database/get",
         tags=["Database"],
         name="",
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
         )
def get_db():
    """Return existing databases list

    Returns:
        APIResponse: code and message about statement status
    """
    try:
        sql = SqlOperation("SHOW DATABASES")
        result = sql.execute()
        return APIResponse(code=200, message="Existing databases", data=result)
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.post("/database/create", tags=["Database"], name="",
          response_model=APIResponse, dependencies=[Depends(auth.get_api_key)])
def create_db(request: DatabaseRequest):
    """Create new database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        APIResponse: code and message about statement status
    """
    try:
        database_name = request.database_name
        sql = SqlOperation(f"CREATE DATABASE {database_name}")
        sql.execute()
        return APIResponse(code=200, message=f"Database {database_name} has been created")
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.delete("/database/delete",
            tags=["Database"],
            name="",
            response_model=APIResponse,
            dependencies=[Depends(auth.get_api_key)]
            )
def delete_db(request: DatabaseRequest):
    """Delete existing database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        APIResponse: code and message about statement status
    """
    try:
        database_name = request.database_name
        sql = SqlOperation(f"DROP DATABASE {database_name}")
        sql.execute()
        return APIResponse(code=200, message=f"Database {database_name} has been deleted")
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))

# ------------------- TABLE ENDPOINTS -------------------


@app.get("/table/get/{database_name}",
         tags=["Table"],
         name="",
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
         )
def get_table(database_name: Identifier):
    """Show existing tables in provided database

    Args:
        database_name (str): database name provided as request query parameter

    Returns:
        APIResponse: code and message about statement status
    """
    try:
        sql = SqlOperation("SHOW TABLES", database_name)
        result = sql.execute()
        return APIResponse(
            code=200, message=f'Existing tables in database {database_name}', data=result)
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.post("/table/create",
          tags=["Table"],
          name="",
          response_model=APIResponse,
          dependencies=[Depends(auth.get_api_key)]
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
    try:
        database_name = request.database_name
        table_name = request.table_name
        columns = request.columns
        columns = ",".join([f"{column.name} {column.params}" for column in columns])
        sql = SqlOperation(f"CREATE TABLE {table_name} ({columns})", database_name)
        sql.execute()
        return APIResponse(
            code=200, message=f'Table {table_name} in database {database_name} has been created')
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.put("/table/rename",
         tags=["Table"],
         name="",
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
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
    try:
        database_name = request.database_name
        old_table_name = request.old_table_name
        new_table_name = request.new_table_name
        sql = SqlOperation(f"RENAME TABLE {old_table_name} TO {new_table_name}", database_name)
        sql.execute()
        return APIResponse(
            code=200,
            message=f"Table {old_table_name} has been renamed to "
                    f"{new_table_name} in database {database_name}"
        )
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.delete("/table/delete",
            tags=["Table"],
            name="",
            response_model=APIResponse,
            dependencies=[Depends(auth.get_api_key)]
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
    try:
        database_name = request.database_name
        table_name = request.table_name
        sql = SqlOperation(f"DROP TABLE {table_name}", database_name)
        sql.execute()
        return APIResponse(
            code=200, message=f'Table {table_name} has been deleted from database {database_name}')
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.get("/table/columns/{database_name}/{table_name}",
         tags=["Table"],
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
         )
def get_table_columns(database_name: Identifier, table_name: Identifier):
    """Get columns for a given table (DESCRIBE table)."""
    try:
        sql = SqlOperation(f"DESCRIBE {table_name}", database_name)
        result = sql.execute()
        return APIResponse(code=200, message=f'Columns for table {table_name}', data=result)
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))

# ------------------- ROW CRUD ENDPOINTS -------------------


@app.post("/row/insert",
          tags=["Table"],
          response_model=APIResponse,
          dependencies=[Depends(auth.get_api_key)]
          )
def insert_row(request: RowInsertRequest):
    """Insert a new record into a table"""
    try:
        columns = ', '.join(request.values.keys())
        placeholders = ', '.join(['%s'] * len(request.values))
        values = tuple(request.values.values())
        sql = SqlOperation(
            f"INSERT INTO {request.table_name} ({columns}) VALUES ({placeholders})",
            request.database_name,
            params=values
        )
        sql.execute()
        return APIResponse(code=200, message='Row inserted')
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.get("/row/get/{database_name}/{table_name}",
         tags=["Table"],
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
         )
def get_rows(database_name: Identifier, table_name: Identifier):
    """Get all records from a table"""
    try:
        sql = SqlOperation(f"SELECT * FROM {table_name}", database_name)
        result = sql.execute()
        return APIResponse(code=200, message='Rows fetched', data=result)
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.put("/row/update",
         tags=["Table"],
         response_model=APIResponse,
         dependencies=[Depends(auth.get_api_key)]
         )
def update_row(request: RowUpdateRequest):
    """Update a record in a table by id"""
    try:
        set_clause = ', '.join([f"{k}=%s" for k in request.values.keys()])
        values = tuple(request.values.values()) + (request.row_id,)
        sql = SqlOperation(
            f"UPDATE {request.table_name} SET {set_clause} WHERE id=%s",
            request.database_name,
            params=values
        )
        sql.execute()
        return APIResponse(code=200, message='Row updated')
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.delete("/row/delete",
            tags=["Table"],
            response_model=APIResponse,
            dependencies=[Depends(auth.get_api_key)]
            )
def delete_row(request: RowDeleteRequest):
    """Delete a record from a table by id"""
    try:
        sql = SqlOperation(
            f"DELETE FROM {request.table_name} WHERE id=%s",
            request.database_name,
            params=(request.row_id,)
        )
        sql.execute()
        return APIResponse(code=200, message='Row deleted')
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))

# ------------------- USER MANAGEMENT ENDPOINTS -------------------


# In-memory user store for demonstration (replace with DB in production)
users = {}
user_id_counter = 1


@app.post("/user",
          tags=["User"],
          response_model=APIResponse,
          summary="Create a new user",
          description="Create a new user. Password is not stored (demo only).",
          dependencies=[Depends(auth.get_api_key)]
          )
async def create_user(user: UserCreate):
    """Create a new user."""
    global user_id_counter
    user_data = user.model_dump()
    user_data.pop("password")  # Do not store password in plain text (for demo only)
    user_data["id"] = user_id_counter
    users[user_id_counter] = user_data
    user_id_counter += 1
    return APIResponse(code=200, message="User created", data=user_data)


@app.get("/user/{user_id}",
         tags=["User"],
         response_model=APIResponse,
         summary="Get user by ID",
         description="Fetch a user by their unique ID.",
         dependencies=[Depends(auth.get_api_key)]
         )
async def get_user(user_id: int):
    """Get user by ID."""
    user = users.get(user_id)
    if not user:
        return APIResponse(code=404, message="User not found")
    return APIResponse(code=200, message="User fetched", data=user)


@app.put("/user/{user_id}",
         tags=["User"],
         response_model=APIResponse,
         summary="Update user by ID",
         description="Update user details by their unique ID.",
         dependencies=[Depends(auth.get_api_key)]
         )
async def update_user(user_id: int, user: UserUpdate):
    """Update user by ID."""
    if user_id not in users:
        return APIResponse(code=404, message="User not found")
    update_data = user.model_dump(exclude_unset=True)
    update_data.pop("password", None)  # Not stored (demo only)
    users[user_id].update(update_data)
    return APIResponse(code=200, message="User updated", data=users[user_id])


@app.delete("/user/{user_id}",
            tags=["User"],
            response_model=APIResponse,
            summary="Delete user by ID",
            description="Delete a user by their unique ID.",
            dependencies=[Depends(auth.get_api_key)]
            )
async def delete_user(user_id: int):
    """Delete user by ID."""
    if user_id not in users:
        return APIResponse(code=404, message="User not found")
    users.pop(user_id)
    return APIResponse(code=200, message="User deleted")

# ------------------- DATABASE BACKUP AND RESTORE ENDPOINTS -------------------


def run_mysql_tool(tool: str, database_name: str, stdin: str = None):
    """Run mysql/mysqldump against the configured server; password is passed via env."""
    cmd = [
        tool,
        f"-h{os.getenv('MYSQL_HOST', 'db')}",
        f"-u{os.getenv('MYSQL_USER', 'root')}",
        "--ssl-verify-server-cert=OFF",
        database_name
    ]
    env = {**os.environ, "MYSQL_PWD": os.getenv("MYSQL_ROOT_PASSWORD", "")}
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env)


@app.post("/database/backup",
          tags=["Database"],
          response_model=APIResponse,
          dependencies=[Depends(auth.get_api_key)]
          )
def backup_database(request: DatabaseBackupRequest):
    """Backup a database and return SQL dump as string."""
    try:
        result = run_mysql_tool("mysqldump", request.database_name)
        if result.returncode != 0:
            return APIResponse(code=500, message=f"mysqldump error: {result.stderr}")
        return APIResponse(code=200, message="Backup successful", data=result.stdout)
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))


@app.post("/database/restore",
          tags=["Database"],
          response_model=APIResponse,
          dependencies=[Depends(auth.get_api_key)]
          )
def restore_database(request: DatabaseRestoreRequest):
    """Restore a database from SQL dump string."""
    try:
        if not request.sql_dump.strip():
            return APIResponse(code=400, message="SQL dump is empty")
        result = run_mysql_tool("mysql", request.database_name, stdin=request.sql_dump)
        if result.returncode != 0:
            return APIResponse(code=500, message=f"mysql error: {result.stderr}")
        return APIResponse(code=200, message="Restore successful")
    except Exception as exc:
        return APIResponse(code=500, message=str(exc))
