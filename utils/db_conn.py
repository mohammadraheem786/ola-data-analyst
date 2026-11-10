
import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()


class DatabaseUtil:

    def __init__(self, db_config=None):

        self.db_config = db_config or {
            "server": os.getenv("DB_SERVER"),
            "database": os.getenv("DB_NAME"),
            "driver": os.getenv(
                "DB_DRIVER",
                "ODBC Driver 18 for SQL Server"
            ),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD")
        }

    # ------------------------------------------------
    # DATABASE CONNECTION
    # ------------------------------------------------

    def get_connection(self):

        config = self.db_config

        connection_string = (
            f"DRIVER={{{config['driver']}}};"
            f"SERVER={config['server']};"
            f"DATABASE={config['database']};"
            "TrustServerCertificate=yes;"
        )

        if not config.get("user"):
            connection_string += "Trusted_Connection=yes;"
        else:
            connection_string += (
                f"UID={config['user']};"
                f"PWD={config['password']};"
            )

        return pyodbc.connect(connection_string)

    # ------------------------------------------------
    # FETCH DATABASE SCHEMA DETAILS
    # ------------------------------------------------

    def schema_details(self, schema_name="dbo"):

        schema_info_context = ""
        connection = None
        cursor = None

        try:

            connection = self.get_connection()
            cursor = connection.cursor()

            schema_info_context = (
                f"Database Schema: {schema_name}\n"
            )

            cursor.execute("""
                SELECT
                    TABLE_NAME,
                    COLUMN_NAME,
                    DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_NAME IN (
                      SELECT TABLE_NAME
                      FROM INFORMATION_SCHEMA.TABLES
                      WHERE TABLE_SCHEMA = ?
                        AND TABLE_TYPE = 'BASE TABLE'
                  )
                ORDER BY TABLE_NAME, ORDINAL_POSITION;
            """, (schema_name, schema_name))

            columns = cursor.fetchall()

            if not columns:
                return ""

            current_table = None

            for table_name, column_name, data_type in columns:

                if table_name != current_table:

                    current_table = table_name

                    schema_info_context += (
                        f"\nTable: {table_name}\n"
                    )

                schema_info_context += (
                    f"  Column: {column_name}, "
                    f"Data Type: {data_type}\n"
                )

        except Exception as e:

            print(f"Error fetching schema details: {e}")

            schema_info_context = (
                f"Error fetching schema details: {e}"
            )

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

        return schema_info_context

    # ------------------------------------------------
    # EXECUTE SQL QUERY
    # ------------------------------------------------

    def execute_sql(self, query, params=None):

        connection = None
        cursor = None

        try:

            connection = self.get_connection()
            cursor = connection.cursor()

            cursor.execute(query, params or ())

            if cursor.description:

                result = cursor.fetchall()

                return str([tuple(row) for row in result])

            connection.commit()

            return "Query executed successfully."

        except Exception as e:

            if connection:
                connection.rollback()

            print(f"Error executing query: {e}")

            return None

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()


# ------------------------------------------------
# MAIN
# ------------------------------------------------

if __name__ == "__main__":

    obj = DatabaseUtil()

    result = obj.schema_details("dbo")

    with open(
        "test_schema_details.txt",
        "w",
        encoding="utf-8"
    ) as f:

        f.write(result)

    print("Database schema details saved successfully!")
    print(result)
