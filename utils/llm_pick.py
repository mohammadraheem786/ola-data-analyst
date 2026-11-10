from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq

MODELS = {
    "low": "openai/gpt-oss-20b",
    "medium": "qwen/qwen3.8-27b",
    "high": "openai/gpt-oss-120b",
}

def pick_llm(level: str) -> ChatGroq:
    """
    Pick an LLM based on the requested level.

    Args:
        level: 'low', 'medium', or 'high'.

    Returns:
        A configured ChatGroq instance.
    """
    key = level.lower()
    if key not in MODELS:
        raise ValueError("Invalid level. Choose from 'low', 'medium', or 'high'.")
    return ChatGroq(model=MODELS[key], temperature=0, max_tokens=1500)


if __name__ == "__main__":
    llm = pick_llm("medium")
    response = llm.invoke("Hello, how are you?")
    print(response.content)