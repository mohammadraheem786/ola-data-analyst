
from pydantic import BaseModel, Field
from typing import Annotated, Literal
from operator import add


class AgentSchema(BaseModel):

    messages: Annotated[list, add] = Field(default_factory=list)

    user_ques: str = Field(
        ...,
        description="User question to be processed by the agent."
    )

     # Target SQL Server schema.
    # Existing usage defaults to dbo.
    workspace_name: str = Field(
        default="dbo",
        description="SQL Server schema containing the data to analyse."
    )

    curated_ques: str = ""

    prompt_query_context: str = ""

    generated_sql_query: str = ""

    is_safe: Literal["Yes", "No"] | None = None

    comments: str = ""

    sql_query_execution_result: str = ""

    final_answer: str = ""


class JudgeSchema(BaseModel):

    answer: Literal["Yes", "No"] = Field(
        ...,
        description="Indicates whether the generated SQL query is safe to execute or not."
    )

    comments: str = Field(
        ...,
        description="Comments provided by the judge regarding the safety of the generated SQL query."
    )

