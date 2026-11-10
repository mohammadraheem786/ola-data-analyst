
"""Load CSV files into an isolated SQL Server workspace."""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from utils.db_conn import DatabaseUtil
from utils.workspace_manager import WorkspaceManager


MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 150


def quote_identifier(value: str) -> str:
    """Safely quote a SQL Server identifier."""
    return "[" + value.replace("]", "]]") + "]"


def safe_identifier(value: str, fallback: str) -> str:
    """Convert a CSV header or filename into a SQL-safe identifier."""
    value = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())

    if not value:
        value = fallback

    if value[0].isdigit():
        value = "col_" + value

    return value[:120]


def unique_headers(headers: list[str]) -> list[str]:
    """Ensure column names are unique after identifier conversion."""
    result = []
    used = set()

    for index, header in enumerate(headers, start=1):
        base = safe_identifier(header, f"column_{index}")
        candidate = base
        suffix = 2

        while candidate.casefold() in used:
            candidate = f"{base[:110]}_{suffix}"
            suffix += 1

        used.add(candidate.casefold())
        result.append(candidate)

    return result


def infer_sql_type(values: list[str]) -> str:
    """Infer a conservative SQL Server data type."""

    nonempty = [
        value.strip()
        for value in values
        if value is not None and value.strip() != ""
    ]

    if not nonempty:
        return "NVARCHAR(MAX)"

    # Integer detection
    if all(re.fullmatch(r"[+-]?\d+", value) for value in nonempty):
        numbers = [int(value) for value in nonempty]

        if all(-(2**31) <= n <= 2**31 - 1 for n in numbers):
            return "INT"

        if all(-(2**63) <= n <= 2**63 - 1 for n in numbers):
            return "BIGINT"

        return "NVARCHAR(MAX)"

    # Decimal detection
    decimal_pattern = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"

    if all(re.fullmatch(decimal_pattern, value) for value in nonempty):
        try:
            decimals = [Decimal(value) for value in nonempty]

            if all(number.is_finite() for number in decimals):
                scales = [
                    max(-number.as_tuple().exponent, 0)
                    for number in decimals
                ]

                integer_digits = [
                    max(
                        len(number.as_tuple().digits)
                        + number.as_tuple().exponent,
                        0,
                    )
                    for number in decimals
                ]

                scale = max(scales)
                precision = max(integer_digits) + scale

                if 1 <= precision <= 38 and scale <= precision:
                    return f"DECIMAL({max(precision, 1)},{scale})"

        except (InvalidOperation, ValueError):
            pass

    # ISO date detection
    try:
        for value in nonempty:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError

        return "DATE"
    except ValueError:
        pass

    # ISO datetime detection
    try:
        for value in nonempty:
            datetime.fromisoformat(value.replace("Z", "+00:00"))

        return "DATETIME2"
    except ValueError:
        pass

    # Preserve values when their type is uncertain.
    return "NVARCHAR(MAX)"


class CSVLoader:

    def __init__(self, db=None):
        self.db = db or DatabaseUtil()
        self.workspaces = WorkspaceManager(self.db)

    def _parse_csv(self, filename, file_obj):
        """Read and validate one CSV before inserting anything."""

        if not filename.lower().endswith(".csv"):
            raise ValueError(f"Unsupported file: {filename}. Only CSV files are allowed.")

        raw = file_obj.read(MAX_FILE_BYTES + 1)

        if isinstance(raw, str):
            encoded = raw.encode("utf-8")
            content = raw
        else:
            encoded = raw
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    f"{filename} must use UTF-8 encoding."
                ) from exc

        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError(f"{filename} exceeds the 20 MB limit.")

        reader = csv.reader(io.StringIO(content))

        try:
            raw_headers = next(reader)
        except StopIteration:
            raise ValueError(f"{filename} is empty.")

        if not raw_headers or all(not header.strip() for header in raw_headers):
            raise ValueError(f"{filename} does not contain valid headers.")

        if len(raw_headers) > MAX_COLUMNS:
            raise ValueError(
                f"{filename} exceeds the {MAX_COLUMNS}-column limit."
            )

        headers = unique_headers(raw_headers)

        rows = []

        for line_number, row in enumerate(reader, start=2):

            if len(row) != len(headers):
                raise ValueError(
                    f"{filename}: malformed row at line {line_number}. "
                    f"Expected {len(headers)} fields, got {len(row)}."
                )

            rows.append([
                value if value != "" else None
                for value in row
            ])

            if len(rows) > MAX_ROWS:
                raise ValueError(
                    f"{filename} exceeds the {MAX_ROWS}-row limit."
                )

        if not rows:
            raise ValueError(f"{filename} contains no data rows.")

        table_name = safe_identifier(
            PurePosixPath(filename.replace("\\", "/")).stem,
            "uploaded_data",
        )

        column_types = [
            infer_sql_type([
                row[index] or ""
                for row in rows
            ])
            for index in range(len(headers))
        ]

        return {
            "table_name": table_name,
            "headers": headers,
            "column_types": column_types,
            "rows": rows,
        }

    def load_multiple(self, workspace_name, files):
        """
        Load multiple CSV files into one workspace.

        All files are validated before database insertion.
        The database changes are committed together.
        """

        if not self.workspaces.workspace_exists(workspace_name):
            raise ValueError("Workspace does not exist.")

        if not files:
            raise ValueError("Upload at least one CSV file.")

        parsed_files = [
            self._parse_csv(filename, file_obj)
            for filename, file_obj in files
        ]

        table_names = [
            item["table_name"].casefold()
            for item in parsed_files
        ]

        if len(table_names) != len(set(table_names)):
            raise ValueError(
                "Multiple uploaded files produce the same table name."
            )

        schema = quote_identifier(workspace_name)
        connection = self.db.get_connection()
        cursor = connection.cursor()

        results = []

        try:
            for item in parsed_files:

                table_name = item["table_name"]
                safe_table = quote_identifier(table_name)

                cursor.execute(
                    """
                    SELECT 1
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = ?
                    AND TABLE_NAME = ?
                    """,
                    (workspace_name, table_name),
                )

                if cursor.fetchone():
                    raise ValueError(
                        f"Table '{table_name}' already exists in this workspace."
                    )

                column_definitions = ", ".join(
                    f"{quote_identifier(name)} {sql_type} NULL"
                    for name, sql_type in zip(
                        item["headers"],
                        item["column_types"],
                    )
                )

                create_sql = (
                    f"CREATE TABLE {schema}.{safe_table} "
                    f"({column_definitions})"
                )

                cursor.execute(create_sql)

                column_list = ", ".join(
                    quote_identifier(name)
                    for name in item["headers"]
                )

                placeholders = ", ".join(
                    "?" for _ in item["headers"]
                )

                insert_sql = (
                    f"INSERT INTO {schema}.{safe_table} "
                    f"({column_list}) VALUES ({placeholders})"
                )

               # Disable fast_executemany to avoid ODBC string-buffer
                # truncation when later rows contain longer strings.
                cursor.fast_executemany = False

                cursor.executemany(insert_sql, item["rows"])

                results.append({
                    "table_name": table_name,
                    "row_count": len(item["rows"]),
                    "columns": [
                        {
                            "name": name,
                            "sql_type": sql_type,
                        }
                        for name, sql_type in zip(
                            item["headers"],
                            item["column_types"],
                        )
                    ],
                })

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        return results

    def load_csv(self, workspace_name, filename, file_obj):
        """Convenience method for loading a single CSV."""

        results = self.load_multiple(
            workspace_name,
            [(filename, file_obj)],
        )

        return results[0]
