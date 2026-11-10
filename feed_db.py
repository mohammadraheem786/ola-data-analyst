import os
import csv
from datetime import date, datetime
from decimal import Decimal

import pyodbc
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================
# .env example:
#   DB_SERVER=localhost\SQLEXPRESS
#   DB_NAME=OlaData
#   DB_USER=your_user            (leave empty to use Windows Authentication)
#   DB_PASSWORD=your_password
#   DB_PORT=1433                 (optional)
#   DB_DRIVER=ODBC Driver 18 for SQL Server   (optional)

CSV_DIR = "data"
CLEAR_EXISTING_DATA = True   # True = wipe all tables before loading
BATCH_SIZE = 5000


def build_connection_string() -> str:
    driver = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    server = os.environ["DB_SERVER"]
    port = os.getenv("DB_PORT")
    if port:
        server = f"{server},{port}"

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={os.environ['DB_NAME']}",
        "TrustServerCertificate=yes",
    ]

    user = os.getenv("DB_USER")
    if user:
        password = os.environ["DB_PASSWORD"].replace("}", "}}")
        parts += [f"UID={user}", f"PWD={{{password}}}"]
    else:
        parts.append("Trusted_Connection=yes")

    return ";".join(parts) + ";"


# ============================================================
# VALUE CONVERTERS (CSV text -> Python types for SQL Server)
# ============================================================

def to_str(v):
    return v


def to_int(v):
    return int(v)


def to_decimal(v):
    return Decimal(v)


def to_bool(v):
    s = v.strip().lower()
    if s in ("t", "true", "1", "yes", "y"):
        return 1
    if s in ("f", "false", "0", "no", "n"):
        return 0
    raise ValueError(f"Cannot convert {v!r} to boolean")


def to_date(v):
    return date.fromisoformat(v.strip()[:10])


def to_datetime(v):
    return datetime.fromisoformat(v.strip())


# ============================================================
# CREATE TABLES
# ============================================================

CREATE_TABLE_STATEMENTS = [
    # USERS
    """
    IF OBJECT_ID(N'dbo.users', N'U') IS NULL
    CREATE TABLE dbo.users (
        user_id INT NOT NULL PRIMARY KEY,
        first_name NVARCHAR(100) NOT NULL,
        last_name NVARCHAR(100) NOT NULL,
        email NVARCHAR(255) NOT NULL UNIQUE,
        phone NVARCHAR(50) NULL,
        city NVARCHAR(100) NULL,
        province NVARCHAR(50) NULL,
        user_type NVARCHAR(20) NOT NULL,
        signup_date DATE NULL,
        is_active BIT NULL
    );
    """,
    # VEHICLES
    """
    IF OBJECT_ID(N'dbo.vehicles', N'U') IS NULL
    CREATE TABLE dbo.vehicles (
        vehicle_id INT NOT NULL PRIMARY KEY,
        driver_id INT NOT NULL,
        make NVARCHAR(50) NULL,
        model NVARCHAR(50) NULL,
        [year] INT NULL,
        license_plate NVARCHAR(20) NULL UNIQUE,
        color NVARCHAR(30) NULL,
        is_active BIT NULL,

        CONSTRAINT fk_vehicle_driver
            FOREIGN KEY (driver_id) REFERENCES dbo.users(user_id)
    );
    """,
    # RIDES
    """
    IF OBJECT_ID(N'dbo.rides', N'U') IS NULL
    CREATE TABLE dbo.rides (
        ride_id INT NOT NULL PRIMARY KEY,

        rider_id INT NOT NULL,
        driver_id INT NOT NULL,

        requested_at DATETIME2 NULL,
        pickup_time DATETIME2 NULL,
        dropoff_time DATETIME2 NULL,

        pickup_latitude DECIMAL(9,6) NULL,
        pickup_longitude DECIMAL(9,6) NULL,

        dropoff_latitude DECIMAL(9,6) NULL,
        dropoff_longitude DECIMAL(9,6) NULL,

        distance_km DECIMAL(10,2) NULL,
        fare DECIMAL(10,2) NULL,
        surge_multiplier DECIMAL(4,2) NULL,

        status NVARCHAR(30) NULL,
        cancellation_reason NVARCHAR(100) NULL,

        CONSTRAINT fk_ride_rider
            FOREIGN KEY (rider_id) REFERENCES dbo.users(user_id),

        CONSTRAINT fk_ride_driver
            FOREIGN KEY (driver_id) REFERENCES dbo.users(user_id)
    );
    """,
    # PAYMENTS
    """
    IF OBJECT_ID(N'dbo.payments', N'U') IS NULL
    CREATE TABLE dbo.payments (
        payment_id INT NOT NULL PRIMARY KEY,

        ride_id INT NOT NULL,
        user_id INT NOT NULL,

        amount DECIMAL(10,2) NULL,

        payment_method NVARCHAR(50) NULL,
        payment_status NVARCHAR(30) NULL,

        transaction_id NVARCHAR(100) NULL UNIQUE,
        payment_time DATETIME2 NULL,

        CONSTRAINT fk_payment_ride
            FOREIGN KEY (ride_id) REFERENCES dbo.rides(ride_id),

        CONSTRAINT fk_payment_user
            FOREIGN KEY (user_id) REFERENCES dbo.users(user_id)
    );
    """,
    # RATINGS
    """
    IF OBJECT_ID(N'dbo.ratings', N'U') IS NULL
    CREATE TABLE dbo.ratings (
        rating_id INT NOT NULL PRIMARY KEY,

        ride_id INT NOT NULL,
        rider_id INT NOT NULL,
        driver_id INT NOT NULL,

        rating INT NULL,
        comment NVARCHAR(MAX) NULL,
        rated_at DATETIME2 NULL,

        CONSTRAINT fk_rating_ride
            FOREIGN KEY (ride_id) REFERENCES dbo.rides(ride_id),

        CONSTRAINT fk_rating_rider
            FOREIGN KEY (rider_id) REFERENCES dbo.users(user_id),

        CONSTRAINT fk_rating_driver
            FOREIGN KEY (driver_id) REFERENCES dbo.users(user_id),

        CONSTRAINT chk_rating
            CHECK (rating BETWEEN 1 AND 5)
    );
    """,
]

# (index name, table, column)
INDEXES = [
    ("idx_vehicles_driver_id", "vehicles", "driver_id"),
    ("idx_rides_rider_id", "rides", "rider_id"),
    ("idx_rides_driver_id", "rides", "driver_id"),
    ("idx_rides_requested_at", "rides", "requested_at"),
    ("idx_rides_status", "rides", "status"),
    ("idx_payments_ride_id", "payments", "ride_id"),
    ("idx_payments_user_id", "payments", "user_id"),
    ("idx_ratings_ride_id", "ratings", "ride_id"),
    ("idx_ratings_driver_id", "ratings", "driver_id"),
]


def index_statement(name: str, table: str, column: str) -> str:
    return f"""
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'{name}' AND object_id = OBJECT_ID(N'dbo.{table}')
    )
    CREATE INDEX {name} ON dbo.{table}({column});
    """


# ============================================================
# TABLE / CSV DEFINITIONS (in load order: parents first)
# ============================================================

TABLES = [
    ("users", "users.csv", [
        ("user_id", to_int),
        ("first_name", to_str),
        ("last_name", to_str),
        ("email", to_str),
        ("phone", to_str),
        ("city", to_str),
        ("province", to_str),
        ("user_type", to_str),
        ("signup_date", to_date),
        ("is_active", to_bool),
    ]),
    ("vehicles", "vehicles.csv", [
        ("vehicle_id", to_int),
        ("driver_id", to_int),
        ("make", to_str),
        ("model", to_str),
        ("year", to_int),
        ("license_plate", to_str),
        ("color", to_str),
        ("is_active", to_bool),
    ]),
    ("rides", "rides.csv", [
        ("ride_id", to_int),
        ("rider_id", to_int),
        ("driver_id", to_int),
        ("requested_at", to_datetime),
        ("pickup_time", to_datetime),
        ("dropoff_time", to_datetime),
        ("pickup_latitude", to_decimal),
        ("pickup_longitude", to_decimal),
        ("dropoff_latitude", to_decimal),
        ("dropoff_longitude", to_decimal),
        ("distance_km", to_decimal),
        ("fare", to_decimal),
        ("surge_multiplier", to_decimal),
        ("status", to_str),
        ("cancellation_reason", to_str),
    ]),
    ("payments", "payments.csv", [
        ("payment_id", to_int),
        ("ride_id", to_int),
        ("user_id", to_int),
        ("amount", to_decimal),
        ("payment_method", to_str),
        ("payment_status", to_str),
        ("transaction_id", to_str),
        ("payment_time", to_datetime),
    ]),
    ("ratings", "ratings.csv", [
        ("rating_id", to_int),
        ("ride_id", to_int),
        ("rider_id", to_int),
        ("driver_id", to_int),
        ("rating", to_int),
        ("comment", to_str),
        ("rated_at", to_datetime),
    ]),
]


# ============================================================
# LOAD CSV (batched inserts with fast_executemany)
# ============================================================

def load_csv(cursor, table_name, csv_file, columns):
    file_path = os.path.join(CSV_DIR, csv_file)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    column_list = ", ".join(f"[{name}]" for name, _ in columns)
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO dbo.[{table_name}] ({column_list}) VALUES ({placeholders})"

    total = 0
    batch = []

    # utf-8-sig strips the BOM if the CSV was saved from Excel
    with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header

        for line_no, row in enumerate(reader, start=2):
            if not row:
                continue

            if len(row) != len(columns):
                raise ValueError(
                    f"{csv_file}, line {line_no}: expected {len(columns)} "
                    f"columns but found {len(row)}"
                )

            try:
                values = tuple(
                    None if raw == "" else convert(raw)
                    for raw, (_, convert) in zip(row, columns)
                )
            except ValueError as e:
                raise ValueError(f"{csv_file}, line {line_no}: {e}") from e

            batch.append(values)

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(insert_sql, batch)
                total += len(batch)
                batch.clear()

        if batch:
            cursor.executemany(insert_sql, batch)
            total += len(batch)

    print(f"Loaded {csv_file} ({total:,} rows)")


# ============================================================
# MAIN
# ============================================================

def main():
    conn = pyodbc.connect(build_connection_string())
    conn.autocommit = False

    cursor = conn.cursor()
    cursor.fast_executemany = True  # set to False if you hit type/size errors

    print("Connected to SQL Server")

    try:
        # Create tables
        for statement in CREATE_TABLE_STATEMENTS:
            cursor.execute(statement)
        for name, table, column in INDEXES:
            cursor.execute(index_statement(name, table, column))
        print("Tables and indexes created successfully")

        # Clear existing data (children first, because of foreign keys)
        if CLEAR_EXISTING_DATA:
            for table_name, _, _ in reversed(TABLES):
                cursor.execute(f"DELETE FROM dbo.[{table_name}];")
            print("Existing data cleared")

        # Load CSVs (parents first)
        for table_name, csv_file, columns in TABLES:
            load_csv(cursor, table_name, csv_file, columns)

        # Verify record counts
        print("\nRecord counts:")
        print("-" * 40)
        for table_name, _, _ in TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM dbo.[{table_name}]")
            count = cursor.fetchone()[0]
            print(f"{table_name:<15} {count:>10,}")

        conn.commit()
        print("\nData loaded successfully!")
        print("Transaction committed.")

    except Exception:
        conn.rollback()
        print("\nError occurred. Transaction rolled back.")
        raise

    finally:
        cursor.close()
        conn.close()
        print("SQL Server connection closed.")


if __name__ == "__main__":
    main()