"""
Multi-model evaluation pipeline.

Tests how well different LLMs generate structured GitHub search queries
against a manually-labeled ground-truth set.

Models evaluated:
  - gpt-4o-mini            (OpenAI, closed-source)          OPENAI_API_KEY
  - llama-3.3-70b          (Meta via Groq, open-weight 70B)  GROQ_API_KEY
  - llama-3.1-8b-instant   (Meta via Groq, open-weight 8B)   GROQ_API_KEY

Usage:
  python eval_pipeline.py                        # run all models
  python eval_pipeline.py --model gpt-4o-mini    # run one model only
  python eval_pipeline.py --save results.json    # save detailed results
"""

import argparse
import json
import os
import sys

from openai import OpenAI

from prompts import SYSTEM_PROMPT, FEW_SHOTS


# ---------------------------------------------------------------------------
# Model definitions
# Each entry describes one model and how to reach it.
# Both Groq models use the OpenAI SDK with a different base_url — no extra
# SDK required.
# ---------------------------------------------------------------------------
MODELS = [
    {
        "id": "gpt-4o-mini",
        "display": "GPT-4o Mini  (OpenAI · closed-source)",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "json_mode": True,
    },
    {
        "id": "llama-3.3-70b-versatile",
        "display": "LLaMA 3.3 70B  (Meta · open-weight · Groq)",
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "json_mode": True,
    },
    {
        "id": "llama-3.1-8b-instant",
        "display": "LLaMA 3.1 8B  (Meta · open-weight · smaller model · Groq)",
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "json_mode": True,
    },
]


# ---------------------------------------------------------------------------
# LLM calling
# ---------------------------------------------------------------------------

def _get_client(model_cfg: dict) -> OpenAI:
    api_key = os.getenv(model_cfg["api_key_env"]) # Replace with your own API key: Open AI / Groq
    if not api_key:
        raise RuntimeError(
            f"Missing env var: {model_cfg['api_key_env']} "
            f"(required for {model_cfg['id']})"
        )
    kwargs = {"api_key": api_key}
    if model_cfg["base_url"]:
        kwargs["base_url"] = model_cfg["base_url"]
    return OpenAI(**kwargs)


def call_model(user_input: str, model_cfg: dict) -> str:
    """Call one model and return the raw string response."""
    client = _get_client(model_cfg)

    create_kwargs = dict(
        model=model_cfg["id"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n" + FEW_SHOTS},
            {"role": "user",   "content": user_input},
        ],
        temperature=0,
        max_tokens=150,
    )
    if model_cfg["json_mode"]:
        create_kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**create_kwargs)
    return response.choices[0].message.content


def safe_parse_json(raw: str) -> dict | None:
    """Try to extract a JSON object from raw model output."""
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Fallback: strip markdown fences that open-weight models sometimes emit
    import re
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def translate_with_model(user_input: str, model_cfg: dict) -> dict | None:
    """Full round-trip: NL query → raw string → parsed dict (or None)."""
    raw = call_model(user_input, model_cfg)
    return safe_parse_json(raw)


# ---------------------------------------------------------------------------
# Test case helpers
# ---------------------------------------------------------------------------

def load_test_cases(path: str) -> list[dict]:
    """Load JSONL test cases. Each line is one JSON object."""
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def normalize_output(output: dict | None) -> dict:
    """
    Normalize a model output to a fixed schema so comparison is field-order
    independent and missing-field safe.

    Key invariants enforced here:
    - keywords: always a list (LLM sometimes returns null instead of [])
    - min_stars: always int or None (coerce float 1000.0 → 1000)
    - limit: always int or None (coerce string "3" → 3)
    """
    if output is None:
        output = {}

    # keywords: treat null/missing/non-list all as []
    kw = output.get("keywords")
    keywords = kw if isinstance(kw, list) else []

    # min_stars: coerce float → int, keep None as None
    min_stars = output.get("min_stars")
    if isinstance(min_stars, float):
        min_stars = int(min_stars)

    # limit: coerce string → int, keep None as None
    limit = output.get("limit")
    if isinstance(limit, str) and limit.isdigit():
        limit = int(limit)
    elif isinstance(limit, float):
        limit = int(limit)

    return {
        "intent":    output.get("intent"),
        "language":  output.get("language"),
        "keywords":  keywords,
        "min_stars": min_stars,
        "sort":      output.get("sort"),
        "order":     output.get("order"),
        "limit":     limit,
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_case(case: dict, model_cfg: dict) -> dict:
    """Run one test case through a model and compare to ground truth."""
    predicted_raw = translate_with_model(case["input"], model_cfg)
    expected   = normalize_output(case["expected"])
    predicted  = normalize_output(predicted_raw)
    is_correct = predicted == expected

    # Debug: print first mismatch in detail so normalization bugs are visible
    if not is_correct and os.getenv("DEBUG"):
        print(f"\n  [DEBUG] {case['id']} – {case['input']}")
        print(f"    RAW    : {predicted_raw}")
        print(f"    EXPECT : {expected}")
        print(f"    PREDICT: {predicted}")
        for k in expected:
            if expected[k] != predicted.get(k):
                print(f"    DIFF [{k}]: expected={expected[k]!r}  got={predicted.get(k)!r}")

    return {
        "id":        case["id"],
        "category":  case["category"],
        "input":     case["input"],
        "expected":  expected,
        "predicted": predicted,
        "correct":   is_correct,
    }


def calculate_category_accuracy(results: list[dict]) -> dict:
    """Return {category: {correct, total}} mapping."""
    stats: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        if cat not in stats:
            stats[cat] = {"correct": 0, "total": 0}
        stats[cat]["total"] += 1
        if r["correct"]:
            stats[cat]["correct"] += 1
    return stats


def run_model_eval(model_cfg: dict, cases: list[dict]) -> dict:
    """
    Run the full evaluation for one model.
    Returns a summary dict that includes per-case results.
    """
    display = model_cfg["display"]
    print(f"\n{'=' * 60}")
    print(f"Model: {display}")
    print("=" * 60)

    results = []
    for case in cases:
        try:
            result = evaluate_case(case, model_cfg)
        except Exception as e:
            print(f"\nEXCEPTION on {case['id']}: {repr(e)}")
            result = {
                "id":        case["id"],
                "category":  case["category"],
                "input":     case["input"],
                "expected":  normalize_output(case["expected"]),
                "predicted": normalize_output(None),
                "correct":   False,
                "error":     str(e),
            }

        results.append(result)
        status = "PASS" if result["correct"] else "FAIL"
        print(f"  [{status}] {result['id']} – {result['input']}")

    total   = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / total if total else 0

    print(f"\n  Accuracy: {accuracy:.2%}  ({correct}/{total})")

    cat_stats = calculate_category_accuracy(results)
    print("  Category breakdown:")
    for cat, s in cat_stats.items():
        cat_acc = s["correct"] / s["total"]
        print(f"    {cat:<14} {s['correct']}/{s['total']}  ({cat_acc:.2%})")

    return {
        "model":    model_cfg["id"],
        "display":  display,
        "accuracy": accuracy,
        "correct":  correct,
        "total":    total,
        "category_stats": cat_stats,
        "results":  results,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_comparison_table(summaries: list[dict]) -> None:
    print(f"\n{'=' * 60}")
    print("COMPARISON SUMMARY")
    print("=" * 60)

    # Header row
    col = 18
    print(f"  {'Model':<40} {'Accuracy':>10}  {'Pass/Total':>12}")
    print(f"  {'-' * 40} {'-' * 10}  {'-' * 12}")

    for s in summaries:
        name = s["model"][:40]
        print(
            f"  {name:<40} {s['accuracy']:>9.2%}  "
            f"{s['correct']:>5}/{s['total']:<5}"
        )

    # Category breakdown across all models
    if len(summaries) > 1:
        all_cats = sorted(
            {cat for s in summaries for cat in s["category_stats"]}
        )
        print(f"\n  {'Category':<14}", end="")
        for s in summaries:
            short = s["model"].split("-")[0][:10]
            print(f"  {short:>10}", end="")
        print()
        print(f"  {'-' * 14}", end="")
        for _ in summaries:
            print(f"  {'-' * 10}", end="")
        print()
        for cat in all_cats:
            print(f"  {cat:<14}", end="")
            for s in summaries:
                cs = s["category_stats"].get(cat, {"correct": 0, "total": 0})
                pct = cs["correct"] / cs["total"] if cs["total"] else 0
                print(f"  {pct:>9.0%} ", end="")
            print()

    # Failed cases (union across all models)
    all_failed: dict[str, dict] = {}
    for s in summaries:
        for r in s["results"]:
            if not r["correct"]:
                key = r["id"]
                if key not in all_failed:
                    all_failed[key] = r
    if all_failed:
        print(f"\n  Cases failed by at least one model:")
        for r in all_failed.values():
            print(f"    [{r['id']}] {r['input']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Multi-model eval pipeline")
    parser.add_argument(
        "--model",
        help="Run only this model ID (default: all models)",
    )
    parser.add_argument(
        "--data",
        default="data/test_cases.jsonl",
        help="Path to JSONL test cases (default: data/test_cases.jsonl)",
    )
    parser.add_argument(
        "--save",
        metavar="FILE",
        help="Save detailed results to this JSON file",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    cases = load_test_cases(args.data)
    print(f"Loaded {len(cases)} test cases from {args.data}")

    models_to_run = MODELS
    if args.model:
        models_to_run = [m for m in MODELS if m["id"] == args.model]
        if not models_to_run:
            print(f"Unknown model: {args.model}")
            print(f"Available: {[m['id'] for m in MODELS]}")
            sys.exit(1)

    summaries = []
    for model_cfg in models_to_run:
        summary = run_model_eval(model_cfg, cases)
        summaries.append(summary)

    if len(summaries) > 1:
        print_comparison_table(summaries)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=False)
        print(f"\nDetailed results saved to {args.save}")


if __name__ == "__main__":
    main()
