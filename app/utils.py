import os
import mysql.connector


class SqlOperation:
    """ MySQl operations """

    def __init__(self, statement: str, database_name: str = None, params: tuple = None):
        self.statement = statement
        self.database_name = database_name
        self.params = params

    def execute(self):
        """Execute SQL statement on MySQL

        Returns:
            list: A list of SQL statement results
        """
        cnx = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST"),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_ROOT_PASSWORD"),
            database=self.database_name,
            autocommit=True
        )
        try:
            cursor = cnx.cursor()
            cursor.execute(self.statement, self.params)
            result = cursor.fetchall()
        finally:
            cnx.close()

        # Parsing SQL statement results to have list as output
        return [row[0] if len(row) == 1 else row for row in result]
