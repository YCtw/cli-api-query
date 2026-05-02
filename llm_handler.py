# LLM Handler to request the LLM API calls and check the output (safe parse json)
import json
import os
from openai import OpenAI
from prompts import SYSTEM_PROMPT, FEW_SHOTS


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Default output if parsing fails
DEFAULT_OUTPUT = {
    "intent": "search_repositories",
    "language": None,
    "keywords": [],
    "min_stars": None,
    "sort": "stars",
    "order": "desc",
    "limit": 5,
}


# Check if the raw output is a valid JSON format
def safe_parse_json(raw_output: str):
    try:
        return json.loads(raw_output)
    except Exception:
        return None


# Call the LLM API
def call_llm(user_input: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {   #Set the system prompt and few shots - Rules and Examples
                "role": "system",
                "content": SYSTEM_PROMPT + "\n" + FEW_SHOTS,
            },
            {   #Set the real user input - Real User Input
                "role": "user",
                "content": user_input,
            },
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=1000,
    )

    return response.choices[0].message.content


# Returns the parsed JSON dict, or None if the LLM output could not be parsed.
# The agent decides what to do on None (retry, fall back, etc.).
def translate_to_query(user_input: str):
    raw_output = call_llm(user_input)
    print("RAW LLM OUTPUT:", raw_output)
    return safe_parse_json(raw_output)
