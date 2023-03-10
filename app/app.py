import logging

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import auth
from utils import SqlOperation
from model import *

__version__ = "1.2.0"

# Request tags
tags_metadata = [
    {
        "name": "API",
    },
    {
        "name": "Database",
    },
    {
        "name": "Table",
    }
]

# Initiate FastAPI with vault API key authentication by "AccessToken" in request header
app = FastAPI(
    title="MySQL API",
    version=__version__,
    dependencies=[Depends(auth.get_api_key)],
    contact={
        "name": "Krzysztof Poltorak",
        "email": "krzysztof@poltorak.pro",
    },
    redoc_url=None,
    docs_url="/",
)

origins = [
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
                    level=logging.INFO)

##################### API routes section #####################

@app.get("/api", tags=["API"], name="")
async def api():
    """Retun API version

    Returns:
        dict: message with API version
    """
    return {"message": f"MySQL API version {__version__}"}

##################### Database routes section #####################

@app.get("/database/get", tags=["Database"], name="")
async def get_db():
    """Return existing databases list

    Returns:
        dict: code and message about statement status
    """
    try:
        sql = SqlOperation("SHOW DATABASES")
        result = sql.execute()

        return {'code': 200, 'message': f"Existing databases: {result}"}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}


@app.post("/database/create", tags=["Database"], name="")
async def create_db(request: DatabaseRequest):
    """Create new database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        dict: code and message about statement status
    """
    try:
        database_name = request.database_name

        sql = SqlOperation(f"CREATE DATABASE {database_name}")
        sql.execute()

        return {'code': 200, 'message': f'Database {database_name} has been created'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}


@app.delete("/database/delete", tags=["Database"], name="")
async def delete_db(request: DatabaseRequest):
    """Delete existing database

    Args:
        request (DatabaseRequest):
            database_name (str): database name

    Returns:
        dict: code and message about statement status
    """
    try:
        database_name = request.database_name

        sql = SqlOperation(f"DROP DATABASE {database_name}")
        sql.execute()

        return {'code': 200, 'message': f'Database {database_name} has been deleted'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}

##################### Table routes section #####################

@app.get("/table/get/{database_name}", tags=["Table"], name="")
async def get_table(database_name):
    """Show existing tables in provided database

    Args:
        database_name (str): database name provided as request query parameter

    Returns:
        dict: code and message about statement status
    """
    try:
        sql = SqlOperation("SHOW TABLES", database_name)
        result = sql.execute()

        return {'code': 200, 'message': f'Existing tables: {result} in database {database_name}'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}


@app.post("/table/create", tags=["Table"], name="")
async def create_table(request: TableCreateRequest):
    """Create table with columns that have constraints

    Args:
        request (TableRequest):
            database_name (str): database name
            table_name (str): table name

    Returns:
        dict: code and message about statement status
    """
    try:
        database_name = request.database_name
        table_name = request.table_name
        columns = request.columns
        columns = ",".join([f"{column.name} {column.params}" for column in columns])
        sql = SqlOperation(f"CREATE TABLE {table_name} ({columns})", database_name)
        sql.execute()

        return {'code': 200, 'message': f'Table {table_name} in database {database_name} has been created'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}


@app.put("/table/rename", tags=["Table"], name="")
async def rename_table(request: TableRenameRequest):
    """Rename existing table name to new one

    Args:
        request (TableRenameRequest):
            database_name (str): database name
            old_table_name (str): existing table name
            new_table_name (str): table name after change

    Returns:
        dict: Code and message about statement status
    """
    try:
        database_name = request.database_name
        old_table_name = request.old_table_name
        new_table_name = request.new_table_name
        sql = SqlOperation(f"RENAME TABLE {old_table_name} TO {new_table_name}", database_name)
        sql.execute()

        return {'code': 200, 'message': f'Table {old_table_name} has been renamed to {new_table_name} in database {database_name}'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}


@app.delete("/table/delete", tags=["Table"], name="")
async def delete_table(request: TableRequest):
    """Delete table if exist

    Args:
        request (TableRequest):
            database_name (str): database name
            table_name (str): table name

    Returns:
        dict: Code and message about statement status
    """

    try:
        database_name = request.database_name
        table_name = request.table_name

        sql = SqlOperation(f"DROP TABLE {table_name}", database_name)
        sql.execute()

        return {'code': 200, 'message': f'Table {table_name} has been deleted from database {database_name}'}

    except Exception as exc:
        return {'code': 500, 'message': str(exc)}
