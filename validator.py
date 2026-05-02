VALID_SORTS = {"stars", "forks", "updated"}

def validate_schema(parsed):
    validated = parsed.copy()

    #If sort is not in VALID_SORTS, force to set it to "stars"
    if validated.get("sort") not in VALID_SORTS:
        validated["sort"] = "stars"

    #If limit is not an integer, force to set it to 5
    if not isinstance(validated.get("limit"), int):
        validated["limit"] = 5

    return validated
