
from utils.workspace_manager import WorkspaceManager
from utils.db_conn import DatabaseUtil

manager = WorkspaceManager()
workspace = "ws_bcae9954329043b98be60eca115abc01"

if not manager.workspace_exists(workspace):
    raise ValueError("Workspace does not exist. Upload the CSV files again.")

query = f"""
SELECT TOP 10
    u.user_id,
    u.first_name,
    u.last_name,
    COUNT(r.rating_id) AS total_ratings,
    CAST(AVG(CAST(r.rating AS FLOAT)) AS DECIMAL(10, 2))
        AS average_rating
FROM [{workspace}].[ratings] AS r
INNER JOIN [{workspace}].[users] AS u
    ON r.rider_id = u.user_id
GROUP BY
    u.user_id,
    u.first_name,
    u.last_name
ORDER BY
    average_rating DESC,
    total_ratings DESC;
"""

result = DatabaseUtil().execute_sql(query)

print("\nTop 10 highest-rated riders:\n")
print(result)
