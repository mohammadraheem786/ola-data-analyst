
from io import BytesIO

from utils.workspace_manager import WorkspaceManager
from utils.csv_loader import CSVLoader
from agents.sql_analyst import sql_analyst


manager = WorkspaceManager()
loader = CSVLoader()

workspace = manager.create_workspace()

print("Workspace created:", workspace)

files = [
    (
        "sales.csv",
        BytesIO(
            b"order_id,product,revenue\n"
            b"1,Laptop,50000\n"
            b"2,Mobile,20000\n"
            b"3,Laptop,60000\n"
        ),
    )
]

try:

    # Load CSV into the new workspace
    upload_results = loader.load_multiple(workspace, files)

    print("\nUploaded files:")
    for item in upload_results:
        print(item)

    # Invoke the compiled LangGraph
    result = sql_analyst.invoke({
        "messages": [],
        "user_ques": "Which product generated the highest total revenue?",
        "workspace_name": workspace
    })

    print("\nGenerated SQL:")
    print(result.get("generated_sql_query"))

    print("\nSafety status:")
    print(result.get("is_safe"))

    print("\nFinal Answer:")
    print(result.get("final_answer"))

finally:
    manager.drop_workspace(workspace)
    print("\nTest workspace deleted.")
