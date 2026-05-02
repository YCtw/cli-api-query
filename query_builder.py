# Query Builder to build the Github API parameters
VALID_SORTS = {"stars", "forks", "updated"}
VALID_ORDERS = {"asc", "desc"}


def _format_keyword(kw: str) -> str:
    """Quote multi-word phrases so GitHub treats them as a single term."""
    kw = kw.strip()
    if " " in kw:
        return f'"{kw}"'
    return kw


def build_github_params(parsed):
    q_parts = []

    # language
    if parsed.get("language"):
        q_parts.append(f"language:{parsed['language'].lower()}")

    # stars filter
    if parsed.get("min_stars") is not None:
        q_parts.append(f"stars:>{parsed['min_stars']}")

    # keywords
    for kw in parsed.get("keywords", []):
        if kw and kw.strip():
            q_parts.append(_format_keyword(kw))

    # fallback (avoid empty query)
    if not q_parts:
        q_parts.append("stars:>0")

    # sort / order / per_page with safe defaults + bounds
    sort = parsed.get("sort", "stars")
    if sort not in VALID_SORTS:
        sort = "stars"

    order = parsed.get("order", "desc")
    if order not in VALID_ORDERS:
        order = "desc"

    limit = parsed.get("limit", 5)
    if not isinstance(limit, int):
        limit = 5
    per_page = max(1, min(limit, 100))

    return {
        "q": " ".join(q_parts),
        "sort": sort,
        "order": order,
        "per_page": per_page,
    }
