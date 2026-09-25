import os
from functools import cache

from mysql.connector.pooling import MySQLConnectionPool


@cache
def get_pool(auth: bool) -> MySQLConnectionPool:
    """Connection pool for the data user (`api`) or the auth user (`api_auth`).

    Created lazily, so importing the app doesn't need a running database.
    """
    # ponytail: fixed size, get_connection() fails (500) instead of waiting when all are busy
    return MySQLConnectionPool(
        pool_name="auth" if auth else "api",
        pool_size=10,
        host=os.getenv("MYSQL_HOST", "db"),
        user="api_auth" if auth else "api",
        password=os.environ["AUTH_DB_PASSWORD" if auth else "DB_PASSWORD"],
        autocommit=True
    )


def query(statement: str, database_name: str = None, params: tuple = None, auth: bool = False):
    """Execute SQL statement on MySQL

    Returns:
        list: rows of the result; single-column rows are flattened to values
    """
    cnx = get_pool(auth).get_connection()
    try:
        if database_name:
            cnx.cmd_init_db(database_name)  # USE <db>
        cursor = cnx.cursor()
        cursor.execute(statement, params)
        result = cursor.fetchall()
    finally:
        cnx.close()  # returns the connection to the pool

    return [row[0] if len(row) == 1 else row for row in result]
