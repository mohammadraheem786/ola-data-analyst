
import os
import re
import sys

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from utils.sql_guard import validate_read_only_workspace_sql
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from utils.db_conn import DatabaseUtil
from utils.workspace_manager import WorkspaceManager
from utils.llm_pick import pick_llm
from Models.schema import AgentSchema, JudgeSchema


# --------------------------------------------------
# 1. Validate selected workspace
# --------------------------------------------------

def get_workspace_name(state: AgentSchema) -> str:
    """
    Allow the existing dbo schema or a valid uploaded workspace.
    """

    workspace_name = state.workspace_name

    if workspace_name == "dbo":
        return workspace_name

    if not re.fullmatch(r"ws_[0-9a-f]{32}", workspace_name):
        raise ValueError("Invalid workspace name.")

    manager = WorkspaceManager()

    if not manager.workspace_exists(workspace_name):
        raise ValueError("Selected workspace does not exist.")

    return workspace_name


# --------------------------------------------------
# 2. Curate user question
# --------------------------------------------------


def curate_ques(state: AgentSchema) -> dict:

    user_question = (state.user_ques or "").strip()

    if not user_question:
        raise ValueError("No question was provided.")

    # Preserve the original question.
    # No LLM call is needed here.
    return {
        "curated_ques": user_question,
        "messages": [
            HumanMessage(
                content=f"User Question: {user_question}"
            )
        ]
    }

# --------------------------------------------------
# 3. Prepare SQL generation context
# --------------------------------------------------


def prompt_query_context(state: AgentSchema) -> dict:

    workspace_name = get_workspace_name(state)

    db = DatabaseUtil()

    schema_info = db.schema_details(workspace_name)

    if (
        not schema_info
        or schema_info.startswith("Error fetching schema details:")
        or "Table:" not in schema_info
    ):
        raise ValueError(
            f"No usable tables were found in workspace '{workspace_name}'."
        )

    prompt = f"""
You are an expert Microsoft SQL Server Data Analyst.

Your task is to convert the user's natural-language question
into ONE valid Microsoft SQL Server T-SQL SELECT statement.

SELECTED WORKSPACE:
{workspace_name}

DATABASE SCHEMA:
{schema_info}


DATABASE SCHEMA QUESTION HANDLING:

1. The DATABASE SCHEMA section already contains all available
   table names, column names and data types.

2. If the user asks which tables or columns are available,
   use the supplied schema information.

3. Never query INFORMATION_SCHEMA, sys.tables, sys.columns
   or other database metadata views.

4. For a column-list question, return the column names as
   string values using UNION ALL.

5. Example:

   SELECT 'ride_id' AS column_name
   UNION ALL
   SELECT 'rider_id' AS column_name;

6. Include every requested column. Do not omit columns or
   invent tables and columns.


ANALYTICAL QUESTION HANDLING:

1. Understand the actual business question before selecting
   tables or columns.

2. Identify all tables required to answer the question.

3. Use JOINs when the required information exists in
   multiple related tables.

4. Use the supplied schema and known relationships to
   identify appropriate join conditions.

5. Consider these candidate relationships when relevant:

   - ratings.rider_id = users.user_id
   - ratings.driver_id = users.user_id
   - ratings.ride_id = rides.ride_id
   - rides.rider_id = users.user_id
   - rides.driver_id = users.user_id
   - payments.ride_id = rides.ride_id
   - payments.user_id = users.user_id

6. For aggregation questions:

   - Use COUNT() for counts.
   - Use SUM() for totals.
   - Use AVG() for averages.
   - Use MIN() and MAX() where appropriate.
   - Use GROUP BY for entity-level aggregation.

7. For ranking questions involving highest, lowest, most,
   least, best or worst:

   - Calculate the requested metric.
   - GROUP BY the entity being ranked.
   - ORDER BY the calculated metric.
   - Use DESC for highest or most.
   - Use ASC for lowest or least.
   - Use TOP when a limited number of results is requested.

8. For average-rating questions, calculate the average
   rating for each relevant entity. Do not simply retrieve
   the latest ratings.

9. When the user asks for a person's name, join the
   appropriate user table instead of returning only an ID.

10. Never substitute a recent-record query for an
    aggregation, comparison or ranking question.

11. Do not invent relationships, business rules or
    column names.


SQL GENERATION RULES:

1. Generate Microsoft SQL Server T-SQL only.

2. Use exact table and column names from the supplied schema.

3. Query ONLY tables belonging to the selected workspace:
   [{workspace_name}].

4. Fully qualify every database table reference using:
   [{workspace_name}].[table_name]

5. Never reference tables from dbo or another schema
   unless dbo is the selected workspace.

6. Generate exactly ONE read-only SELECT statement.

7. CTEs, JOINs, GROUP BY, HAVING, ORDER BY,
   DISTINCT, TOP and UNION ALL are allowed.

8. Do not generate INSERT, UPDATE, DELETE, DROP,
   ALTER, CREATE, TRUNCATE, MERGE, EXEC, CALL
   or other data-modification statements.

9. Do not use SELECT INTO.

10. Do not use LIMIT. Use TOP (10) when the user
    does not specify a different result limit and
    a limited result is appropriate.

11. Do not add unnecessary columns or joins.

12. Use meaningful aliases for calculated columns.

13. Handle NULL values appropriately when required.

14. Never generate a query based on assumptions when
    the supplied schema does not support the requested
    analysis.

15. Return ONLY executable SQL.

16. Do not include Markdown code fences or explanations.


USER QUESTION:
{state.curated_ques}


Generate the SQL query that correctly answers the user's
business question using the supplied database schema.
"""

    return {
        "prompt_query_context": prompt
    }


# --------------------------------------------------
# 4. Generate SQL query
# --------------------------------------------------

def generate_sql_query(state: AgentSchema) -> dict:

    llm = pick_llm("high")

    response = llm.invoke(state.prompt_query_context)

    sql_query = response.content.strip()

    # Remove Markdown code fences if present.
    if sql_query.startswith("```"):

        lines = sql_query.splitlines()

        if lines and lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]

        sql_query = "\n".join(lines).strip()

    return {
        "generated_sql_query": sql_query,
        "messages": [
            AIMessage(
                content=f"Generated SQL Query: {sql_query}"
            )
        ]
    }


# --------------------------------------------------
# 5. Check SQL safety
# --------------------------------------------------

def is_Safe_SQL_query(state: AgentSchema) -> dict:

    try:

        llm = pick_llm("medium")

        llm_judge = llm.with_structured_output(
            JudgeSchema,
            method="json_mode"
        )

        sql_query = state.generated_sql_query

        prompt = f"""
        You are a SQL security judge for Microsoft SQL Server.

        Evaluate whether the following SQL query is safe.

        RULES:

        1. Allow exactly one read-only SELECT statement.
        2. Allow CTEs, DISTINCT and TOP.
        3. Reject INSERT, UPDATE, DELETE, DROP, ALTER,
           CREATE, TRUNCATE, MERGE, EXEC and CALL.
        4. Reject SELECT INTO.
        5. Reject multiple SQL statements.
        6. Reject system procedures and dynamic SQL.
        7. Reject anything unclear or potentially dangerous.

        SELECTED WORKSPACE:
        {state.workspace_name}

        The query must access only tables belonging to:
        [{state.workspace_name}].

        Reject references to other schemas.

        Return valid JSON using this structure:

        {{
            "answer": "Yes or No",
            "comments": "Short explanation"
        }}

        SQL QUERY:
        {sql_query}
        """

        response = llm_judge.invoke(prompt)

        return {
            "is_safe": response.answer,
            "comments": response.comments
        }

    except Exception as error:

        return {
            "is_safe": "No",
            "comments": (
                f"SQL safety validation failed: {str(error)}"
            )
        }


# --------------------------------------------------
# 6. Cancel unsafe SQL
# --------------------------------------------------

def canceled_sql_query(state: AgentSchema) -> dict:

    final_answer = (
        "The requested analysis could not be completed "
        "because the generated operation did not pass "
        f"the safety checks. Reason: {state.comments}"
    )

    return {
        "final_answer": final_answer,
        "messages": [
            AIMessage(content=final_answer)
        ]
    }


# --------------------------------------------------
# 7. Execute safe SQL
# --------------------------------------------------


def execute_sql_query(state: AgentSchema) -> dict:

    sql_query = state.generated_sql_query
    workspace_name = state.workspace_name

    # Check 1: Explicitly require the LLM decision to be "Yes".
    if str(state.is_safe).strip().lower() != "yes":
        return {
            "sql_query_execution_result": (
                "Query blocked because it failed the LLM safety review."
            )
        }

    # Check 2: Deterministic SQL validation.
    is_valid, validation_message = validate_read_only_workspace_sql(
        sql_query=sql_query,
        workspace_name=workspace_name
    )

    if not is_valid:
        return {
            "sql_query_execution_result": (
                f"Query blocked: {validation_message}"
            )
        }

    # Execute only after both checks pass.
    execution_result = DatabaseUtil().execute_sql(sql_query)

    if execution_result is None:
        return {
            "sql_query_execution_result": (
                "Query execution failed. Please check the SQL and database."
            )
        }

    return {
        "sql_query_execution_result": execution_result
    }

# --------------------------------------------------
# 8. Represent final business-friendly answer
# --------------------------------------------------
def represent_final_answer(state: AgentSchema) -> dict:

    execution_result = state.sql_query_execution_result

    # Handle empty or failed execution results
    if not execution_result:
        final_answer = (
            "I couldn't retrieve the requested information. "
            "Please try rephrasing your question."
        )

    elif str(execution_result).startswith("SQL execution failed:"):
        final_answer = (
            "I couldn't retrieve the requested information. "
            "Please try rephrasing your question."
        )

    elif str(execution_result).startswith("SQL execution blocked"):
        final_answer = (
            "The requested analysis could not be completed "
            "because it did not pass the safety checks."
        )

    else:
        # Convert result to string
        execution_result = str(execution_result)

        # Prevent excessively large prompts
        max_result_length = 12000

        if len(execution_result) > max_result_length:
            execution_result = (
                execution_result[:max_result_length]
                + "\n[Results truncated for response generation.]"
            )

        llm = pick_llm("low")

        prompt = f"""
You are a professional Business Data Analyst.

Answer the user's question using ONLY the supplied results.

USER QUESTION:
{state.curated_ques}

DATABASE RESULTS:
{execution_result}

INSTRUCTIONS:
1. Answer the user's actual question directly.
2. Never invent values or conclusions.
3. Avoid technical terms such as SQL, query, database, table and column.
4. Use simple, professional business language.
5. Use bullet points when presenting multiple values.
6. If no matching information was found, say so clearly.
7. Do not add generic introductions or conclusions.
8. Keep the answer concise.

Return only the final client-facing response.
"""

        response = llm.invoke(prompt)
        final_answer = response.content.strip()

    return {
        "final_answer": final_answer,
        "messages": [
            AIMessage(content=f"Final Answer: {final_answer}")
        ]
    }

# --------------------------------------------------
# 9. Conditional routing
# --------------------------------------------------

def is_safe_sql_edge(state: AgentSchema) -> str:

    if state.is_safe == "Yes":
        return "execute_sql_query"

    return "canceled_sql_query"


# --------------------------------------------------
# 10. Build LangGraph
# --------------------------------------------------

sql_agent_graph = StateGraph(AgentSchema)

sql_agent_graph.add_node("curate_ques", curate_ques)

sql_agent_graph.add_node(
    "prompt_query_context",
    prompt_query_context
)

sql_agent_graph.add_node(
    "generate_sql_query",
    generate_sql_query
)

sql_agent_graph.add_node(
    "is_Safe_SQL_query",
    is_Safe_SQL_query
)

sql_agent_graph.add_node(
    "canceled_sql_query",
    canceled_sql_query
)

sql_agent_graph.add_node(
    "execute_sql_query",
    execute_sql_query
)

sql_agent_graph.add_node(
    "represent_final_answer",
    represent_final_answer
)


# Sequential edges

sql_agent_graph.add_edge(
    START,
    "curate_ques"
)

sql_agent_graph.add_edge(
    "curate_ques",
    "prompt_query_context"
)

sql_agent_graph.add_edge(
    "prompt_query_context",
    "generate_sql_query"
)

sql_agent_graph.add_edge(
    "generate_sql_query",
    "is_Safe_SQL_query"
)


# Conditional edges

sql_agent_graph.add_conditional_edges(
    "is_Safe_SQL_query",
    is_safe_sql_edge,
    {
        "execute_sql_query": "execute_sql_query",
        "canceled_sql_query": "canceled_sql_query"
    }
)


# Final edges

sql_agent_graph.add_edge(
    "canceled_sql_query",
    END
)

sql_agent_graph.add_edge(
    "execute_sql_query",
    "represent_final_answer"
)

sql_agent_graph.add_edge(
    "represent_final_answer",
    END
)


# --------------------------------------------------
# 11. Compile and run
# --------------------------------------------------

sql_analyst = sql_agent_graph.compile()


if __name__ == "__main__":

    input_schema = {
        "messages": [],
        "user_ques": (
            "What are the different payment methods "
            "available for customers?"
        ),
        "workspace_name": "dbo"
    }

    result = sql_analyst.invoke(input_schema)

    print("\nGenerated SQL:")
    print(result.get("generated_sql_query"))

    print("\nSafety status:")
    print(result.get("is_safe"))

    print("\nSafety comments:")
    print(result.get("comments"))

    print("\nExecution result:")
    print(
        result.get(
            "sql_query_execution_result",
            "Query was not executed."
        )
    )

    print("\nFinal answer:")
    print(
        result.get(
            "final_answer",
            "No final answer generated."
        )
    )
