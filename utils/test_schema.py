
from utils.db_conn import DatabaseUtil

db = DatabaseUtil()

schema = db.schema_details("dbo")

print(schema)
print("\nSchema character count:", len(schema))
