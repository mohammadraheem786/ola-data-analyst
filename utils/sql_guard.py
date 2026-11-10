from sqlglot import exp, parse


def validate_read_only_workspace_sql(
    sql_query: str,
    workspace_name: str
) -> tuple[bool, str]:
    """
    Validate that SQL contains exactly one SELECT statement
    and accesses only tables in the active workspace schema.
    """

    if not sql_query or not sql_query.strip():
        return False, "SQL query is empty."

    if not workspace_name:
        return False, "Workspace name is missing."

    try:
        statements = parse(sql_query, read="tsql")
        statements = [
            statement
            for statement in statements
            if statement is not None
        ]

        # Exactly one statement is allowed.
        if len(statements) != 1:
            return False, "Only one SQL statement is allowed."

        query = statements[0]

        # Only SELECT statements are allowed.
        # Allow a normal SELECT or a UNION / UNION ALL
# whose query components are SELECT statements.
        if not isinstance(query, (exp.Select, exp.Union)):
            return False, "Only SELECT queries are permitted."

        if isinstance(query, exp.Union):
            select_parts = list(query.find_all(exp.Select))

            if len(select_parts) < 2:
                return False, "Invalid UNION query."

        # SELECT INTO can create a table, so reject it.
        if query.find(exp.Into):
            return False, "SELECT INTO is not permitted."

        # Collect CTE names so their references aren't mistaken
        # for unqualified database tables.
        cte_names = {
            cte.alias.lower()
            for cte in query.find_all(exp.CTE)
            if cte.alias
        }

        # Check every table reference, including nested queries.
        for table in query.find_all(exp.Table):

            # Reject table-valued functions and unusual table sources.
            if not isinstance(table.this, exp.Identifier):
                return False, "Table-valued functions are not permitted."

            table_name = table.name.lower()
            schema_name = table.db

            # An unqualified table is allowed only when it refers
            # to a CTE defined inside this query.
            if not schema_name:
                if table_name in cte_names and not table.catalog:
                    continue

                return False, (
                    "Every database table must explicitly specify "
                    "the active workspace schema."
                )

            # Reject access to other schemas.
            if schema_name.strip("[]").lower() != workspace_name.lower():
                return False, (
                    f"Access to schema '{schema_name}' is not permitted. "
                    f"Only '{workspace_name}' is allowed."
                )

            # Reject cross-database references.
            if table.catalog:
                return False, "Cross-database queries are not permitted."

        return True, "Query passed deterministic SQL validation."

    except Exception as error:
        return False, f"SQL validation failed: {str(error)}"