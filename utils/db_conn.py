
import os
import pyodbc
from dotenv import load_dotenv


# Load local environment variables.
# On Streamlit Cloud, credentials will come from Streamlit Secrets.
load_dotenv()


def get_setting(key, default=None):
    """
    Read configuration in this order:
    1. Environment variables (.env locally)
    2. Streamlit Secrets (deployed application)
    3. Default value
    """

    value = os.getenv(key)

    if value is not None:
        return value

    try:
        import streamlit as st

        value = st.secrets.get(key, default)
        return value

    except Exception:
        return default


def odbc_value(value):
    """
    Escape an ODBC connection-string value.
    """

    value = str(value)

    if ";" in value or "}" in value or "{" in value:
        return "{" + value.replace("}", "}}") + "}"

    return value


class DatabaseUtil:

    def __init__(self, db_config=None):

        self.db_config = db_config or {
            "server": get_setting("DB_SERVER"),
            "database": get_setting("DB_NAME"),
            "driver": get_setting(
                "DB_DRIVER",
                "ODBC Driver 18 for SQL Server"
            ),
            "user": get_setting("DB_USER"),
            "password": get_setting("DB_PASSWORD"),
            "encrypt": get_setting("DB_ENCRYPT", "yes"),
            "trust_server_certificate": get_setting(
                "DB_TRUST_SERVER_CERTIFICATE",
                "no"
            ),
            "connection_timeout": int(
                get_setting("DB_CONNECTION_TIMEOUT", "30")
            )
        }

    # ------------------------------------------------
    # DATABASE CONNECTION
    # ------------------------------------------------

    def get_connection(self):

        config = self.db_config

        required_fields = ["server", "database"]

        for field in required_fields:
            if not config.get(field):
                raise ValueError(
                    f"Missing database configuration: {field}"
                )

        connection_string = (
            f"DRIVER={{{config['driver']}}};"
            f"SERVER={odbc_value(config['server'])};"
            f"DATABASE={odbc_value(config['database'])};"
            f"Encrypt={config.get('encrypt', 'yes')};"
            f"TrustServerCertificate="
            f"{config.get('trust_server_certificate', 'no')};"
            f"Connection Timeout="
            f"{config.get('connection_timeout', 30)};"
        )

        if config.get("user"):

            if not config.get("password"):
                raise ValueError(
                    "Database password is missing."
                )

            connection_string += (
                f"UID={odbc_value(config['user'])};"
                f"PWD={odbc_value(config['password'])};"
            )

        else:

            connection_string += "Trusted_Connection=yes;"

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

                return str([
                    tuple(row) for row in result
                ])

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
