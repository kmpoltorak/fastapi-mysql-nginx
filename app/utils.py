import os
import mysql.connector


class SqlOperation:
    """ MySQl operations """

    def __init__(self, statement: str, database_name: str = None):
        # Get statement variables
        self.statement = statement
        self.database_name = database_name

    def execute(self):
        """Execute SQL statement on MySQL

        Args:
            statement (str): Statement to make operation on MySQL

        Returns:
            list: A list of SQL statement results
        """

        # Connect to MySQL host and make operation
        if self.database_name is not None:
            cnx = mysql.connector.connect(host=os.getenv("MYSQL_HOST"),
                user=os.getenv("MYSQL_USER"),password=os.getenv("MYSQL_ROOT_PASSWORD"),
                database=self.database_name, autocommit=True)
        else:
            cnx = mysql.connector.connect(host=os.getenv("MYSQL_HOST"),
                user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_ROOT_PASSWORD"),
                autocommit=True)
        cursor = cnx.cursor()
        cursor.execute(self.statement)
        result = cursor.fetchall()
        cursor.close()
        cnx.close()

        # Parsing SQL statement results to have list as output
        result_list = []
        for _ in result:
            result_list.append(_[0])

        return result_list
