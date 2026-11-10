import streamlit as st
from io import BytesIO

from utils.workspace_manager import WorkspaceManager
from utils.csv_loader import CSVLoader
from agents.sql_analyst import sql_analyst


# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Ola Data Analyst",
    page_icon="📊",
    layout="wide"
)


# --------------------------------------------------
# INITIALIZE BACKEND COMPONENTS
# --------------------------------------------------

manager = WorkspaceManager()
loader = CSVLoader()


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "workspace_name" not in st.session_state:
    st.session_state.workspace_name = None

if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []

if "upload_results" not in st.session_state:
    st.session_state.upload_results = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "latest_sql" not in st.session_state:
    st.session_state.latest_sql = None

if "sql_executed" not in st.session_state:
    st.session_state.sql_executed = False


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def remove_workspace(workspace_name):
    """Delete only the specified temporary workspace."""

    if workspace_name:
        try:
            manager.drop_workspace(workspace_name)
        except Exception as error:
            st.error(f"Could not remove workspace: {error}")


def reset_analysis():
    """Clear the current workspace and conversation."""

    current_workspace = st.session_state.workspace_name

    remove_workspace(current_workspace)

    st.session_state.workspace_name = None
    st.session_state.uploaded_files = []
    st.session_state.upload_results = []
    st.session_state.chat_history = []
    st.session_state.latest_sql = None
    st.session_state.sql_executed = False


# --------------------------------------------------
# HEADER
# --------------------------------------------------

st.title("Ola Data Analyst")

st.caption(
    "Ask questions about your data and get answers "
    "powered by SQL and Agentic AI."
)

st.divider()


# --------------------------------------------------
# THREE-PANEL LAYOUT
# --------------------------------------------------

left_panel, center_panel, right_panel = st.columns(
    [0.9, 1.8, 1.2],
    gap="medium"
)


# ==================================================
# LEFT PANEL - CSV UPLOAD
# ==================================================

with left_panel:

    st.subheader("Upload Data")

    st.write(
        "Upload clean and structured CSV files "
        "to start your analysis."
    )

    uploaded_files = st.file_uploader(
        "Choose CSV files",
        type=["csv"],
        accept_multiple_files=True,
        help="You can upload multiple related CSV files."
    )

    if st.button(
        "Upload and Analyze",
        use_container_width=True,
        type="primary",
        disabled=not uploaded_files
    ):

        new_workspace = None

        try:
            with st.spinner("Creating workspace and loading data..."):

                # Create an isolated SQL workspace.
                new_workspace = manager.create_workspace()

                # Convert Streamlit uploaded files into file-like objects.
                files_to_load = [
                    (
                        file.name,
                        BytesIO(file.getvalue())
                    )
                    for file in uploaded_files
                ]

                # Load all CSV files into the new workspace.
                upload_results = loader.load_multiple(
                    new_workspace,
                    files_to_load
                )

                # Only replace the previous workspace after
                # the new upload succeeds.
                old_workspace = st.session_state.workspace_name

                st.session_state.workspace_name = new_workspace
                st.session_state.uploaded_files = [
                    file.name for file in uploaded_files
                ]
                st.session_state.upload_results = upload_results

                # Reset previous conversation and SQL.
                st.session_state.chat_history = []
                st.session_state.latest_sql = None
                st.session_state.sql_executed = False

                # Remove the previous workspace.
                if old_workspace:
                    remove_workspace(old_workspace)

            st.success("Data uploaded successfully!")

        except Exception as error:

            # Remove only the failed new workspace.
            if new_workspace:
                remove_workspace(new_workspace)

            st.error(f"Upload failed: {error}")

    # Show upload information.
    if st.session_state.workspace_name:

        st.divider()

        st.success("Workspace ready")

        st.caption("Uploaded files")

        for filename in st.session_state.uploaded_files:
            st.write(f"📄 {filename}")

        st.caption("Loaded tables")

        for item in st.session_state.upload_results:
            st.write(
                f"**{item['table_name']}** — "
                f"{item['row_count']:,} rows"
            )

        st.divider()

        if st.button(
            "Clear Workspace",
            use_container_width=True
        ):
            reset_analysis()
            st.rerun()

    else:

        st.info("Upload CSV files to begin.")


# ==================================================
# CENTER PANEL - AI CHAT
# ==================================================

with center_panel:

    st.subheader("Chat with Ola AI")

    st.caption(
        "Ask business questions using natural language."
    )

    # Display conversation history.
    chat_container = st.container()

    with chat_container:

        if not st.session_state.chat_history:

            st.info(
                "Welcome! Upload your data and ask your first question."
            )

        else:

            for message in st.session_state.chat_history:

                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

    st.divider()

    # Chat input and submit button.
    with st.form(
        key="question_form",
        clear_on_submit=True
    ):

        user_question = st.text_input(
            "Your question",
            placeholder="e.g. Which product generated the highest revenue?",
            label_visibility="collapsed"
        )

        submitted = st.form_submit_button(
            "Send",
            use_container_width=True,
            type="primary"
        )

    if submitted:

        if not st.session_state.workspace_name:

            st.warning("Please upload your CSV files first.")

        elif not user_question.strip():

            st.warning("Please enter a question.")

        else:

            # Add the user's question to chat history.
            st.session_state.chat_history.append({
                "role": "user",
                "content": user_question
            })

            try:

                with st.spinner("Ola AI is analyzing your data..."):

                    # Invoke the existing LangGraph SQL Analyst.
                    result = sql_analyst.invoke({

                        "messages": [],

                        "user_ques": user_question,

                        "workspace_name": (
                            st.session_state.workspace_name
                        )
                    })
                    print("USER QUESTION:", repr(user_question))
                    print("CURATED QUESTION:", repr(result.get("curated_ques")))
                    print("PROMPT QUESTION:", result.get("prompt_query_context", "")[-500:])
                    print("GENERATED SQL:", result.get("generated_sql_query"))

                    final_answer = result.get("final_answer")

                    generated_sql = result.get(
                        "generated_sql_query"
                    )

                    execution_result = result.get(
                        "sql_query_execution_result"
                    )

                    is_safe = result.get("is_safe")

                    # Determine whether the query was blocked.
                    query_blocked = (
                        isinstance(execution_result, str)
                        and execution_result.startswith("Query blocked")
                    )

                    # Save the exact generated SQL.
                    st.session_state.latest_sql = generated_sql

                    # Only label it executed when execution returned
                    # a non-None result and it was not blocked.
                    st.session_state.sql_executed = (
                    bool(generated_sql)
                    and str(is_safe).strip().lower() == "yes"
                    and not query_blocked
                    and execution_result is not None
                    and not str(execution_result).startswith("SQL execution failed:")
                    )

                    if final_answer:
                        answer = str(final_answer)
                    elif query_blocked:
                        answer = (
                            "I couldn't execute this query because "
                            "it did not pass the SQL safety checks."
                        )
                    else:
                        answer = (
                            "I couldn't generate an answer for this question. "
                            "Please try rephrasing it."
                        )

                    # Save the AI response.
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer
                    })

            except Exception as error:

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": (
                        f"Sorry, I encountered an error: {error}"
                    )
                })

            # Refresh the interface to show the latest answer and SQL.
            st.rerun()


# ==================================================
# RIGHT PANEL - GENERATED SQL
# ==================================================

with right_panel:

    st.subheader("SQL Query")

    st.caption(
        "The SQL generated for the latest question."
    )

    if st.session_state.latest_sql:

        if st.session_state.sql_executed:
            st.success("Executed successfully")
        else:
            st.warning("Not confirmed as executed")

        # st.code includes a built-in copy button.
        st.code(
            st.session_state.latest_sql,
            language="sql",
            line_numbers=True
        )

    else:

        st.info(
            "Your generated SQL query will appear here "
            "after you ask a question."
        )