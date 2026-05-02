from llm_handler import translate_to_query, DEFAULT_OUTPUT
from validator import validate_schema


def refine_prompt(user_input: str, prev_output) -> str:
    return f"""
Previous output was invalid (not parseable JSON or missing required fields):
{prev_output}

Please return a corrected JSON object that strictly matches the schema.
Return ONLY JSON, no explanation.

User input: {user_input}
"""


def run_agent(user_input: str, max_retries: int = 2) -> dict:
    current_input = user_input

    for attempt in range(max_retries):
        # Call the LLM API to translate the user input to the structured query
        parsed = translate_to_query(current_input)  

        if parsed is not None:
            # Check if the structured query is valid
            return validate_schema(parsed)  

        # Validate failed: build a refine prompt and try again
        current_input = refine_prompt(user_input, parsed)

    # All retries exhausted: return the safe default so the rest of the pipeline still works
    return DEFAULT_OUTPUT
