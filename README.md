# NL → GitHub CLI

A command-line tool that converts natural language queries into structured GitHub Search API requests, executes them, and returns results.

---

## Project Structure

```
.
├── main.py            # CLI entry point
├── agent.py           # Orchestration: LLM call → validate → return
├── llm_handler.py     # OpenAI API wrapper + JSON parsing
├── prompts.py         # System prompt + few-shot examples
├── validator.py       # Schema healing (sort/limit normalization)
├── query_builder.py   # Structured JSON → GitHub API params
├── github_client.py   # HTTP execution against GitHub Search API
├── eval_pipeline.py   # Multi-model evaluation pipeline (Part 2)
└── data/
    └── test_cases.jsonl  # 30 ground-truth test cases
```

---

## Setup

```bash
pip install openai requests
```

Set environment variables (Use your own):

**Mac / Linux (bash / zsh)**
```bash
export OPENAI_API_KEY="sk-..."
export GITHUB_TOKEN="ghp_..."      # optional but raises rate limit from 10 to 30 req/min
export GROQ_API_KEY="gsk_..."      # required for open-weight models in eval pipeline
```

**Windows Command Prompt**
```cmd
set OPENAI_API_KEY=sk-...
set GITHUB_TOKEN=ghp_...
set GROQ_API_KEY=gsk_...
```

**Windows PowerShell**
```powershell
$env:OPENAI_API_KEY="sk-..."
$env:GITHUB_TOKEN="ghp_..."
$env:GROQ_API_KEY="gsk_..."
```

### Basic Usage

```bash
python main.py "top 5 python repos with more than 1000 stars"
python main.py "most forked javascript repositories"
python main.py "latest golang projects"
python main.py "機器學習 repos"
```

---

## Part 1: Build It, Break It, Harden It

### Architecture Overview

The pipeline follows a linear flow:

```
User NL Input
     ↓
llm_handler.translate_to_query()    # NL → structured JSON via GPT-4o-mini
     ↓
validator.validate_schema()         # heal invalid sort/limit values
     ↓
query_builder.build_github_params() # JSON → GitHub API params (q, sort, order, per_page)
     ↓
github_client.search_repositories() # HTTP GET → GitHub Search API
     ↓
Printed results
```

### Baseline Execution

The core tool converts a natural language query into a structured JSON intent object, then maps it to the GitHub Search Repositories API.

**Internal schema produced by the LLM:**

```json
{
  "intent": "search_repositories",
  "language": "python",
  "keywords": ["machine learning"],
  "min_stars": 1000,
  "sort": "stars",
  "order": "desc",
  "limit": 5
}
```

This maps directly to GitHub API parameters: `q=language:python "machine learning" stars:>1000&sort=stars&order=desc&per_page=5`.

---

## Break It — Failure Cases Discovered

### 1. Ambiguous Input

**Problem:** Queries containing only subjective adjectives (`"cool"`, `"good"`, `"interesting"`) carry no actionable information for structured search.

| Input | Behavior |
|---|---|
| `"good python repos"` | "good" discarded → valid Python search |
| `"cool projects"` | All signals discarded → fallback `stars:>0` |
| `"interesting backend repos"` | "interesting" dropped, "backend" kept → works |

**Resolution:** The prompt is instructed to filter a hard-coded stop-word list and preserve only domain-relevant keywords. When no signals survive filtering, `query_builder` injects `stars:>0` as a fallback to prevent GitHub returning a 422 on an empty `q=` parameter. The tool prioritizes stability over attempting to over-interpret vague intent.

---

### 2. Conflicting Constraints

**Problem:** GitHub's Search API accepts only one `sort` parameter, but users often express multiple ranking signals simultaneously (e.g., "top repos but show newest").

| Input | Challenge |
|---|---|
| `"top python repos but sort by latest"` | `stars` vs `updated` |
| `"most forked repos but show newest"` | `forks` vs `updated` |
| `"I want top repos but also the most recent ones"` | `stars` vs `updated` |

**Resolution:** A conflict resolution strategy was embedded in the prompt:

1. **One winner:** The phrase after `but`, `sort by`, `sorted by`, or `show` wins. Without a marker, priority is `updated > stars > forks`.
2. **Preserve losing signals:** If `top`/`best`/`popular` loses, set `min_stars=100` as a soft popularity floor. If `most forked` loses, drop it (no `min_forks` in the schema).
3. **No date filters:** Recency is expressed only as `sort=updated`; invented fields like `created:>...` are explicitly forbidden.

**Examples after hardening:**

```
Input:  "top python repos but sort by latest"
Output: sort=updated, min_stars=100, language=python
→ q=language:python stars:>100&sort=updated

Input:  "most forked repos but show newest"
Output: sort=updated, min_stars=null
→ q=stars:>0&sort=updated
```

---

### 3. Typos

**Problem:** Real user input contains spelling mistakes at multiple levels: language names, sort signals, keywords, and limit expressions.

| Input | Typo Type | Outcome |
|---|---|---|
| `"top pyhton repos"` | Language (`pyhton` → `python`) | ✅ Corrected |
| `"latset python repos"` | Sort signal (`latset` → `latest`) | ✅ Corrected |
| `"populer python repos"` | Sort signal (`populer` → `popular`) | ✅ Corrected |
| `"tp3 python repos"` | Limit (`tp3` → `top 3`) | ✅ Corrected |
| `"i want bst pyhton repo latset plz"` | Multiple overlapping typos | ✅ Correctly resolves as conflict: `sort=updated, min_stars=100` |
| `"asdfgh python qwer"` | Nonsense tokens | ✅ Extracts `language=python`, discards rest |
| `"top machien learning repos"` | Keyword phrase (`machien learning`) | ❌ Initially preserved as-is (Fixed) |

**Language and sort typos** are handled by the LLM's contextual reasoning without a separate spell-checker. Explicit normalization rules in the prompt cover the most common aliases (`golang` → `go`, `py` → `python`, etc.).

**Keyword typos** were a distinct failure mode. "machien learning" was passed directly into the query, producing near-zero results from the GitHub API. This was fixed by adding an explicit instruction to the prompt:

> *Correct obvious keyword typos when the phrase is recognizable: "machien learning" → "machine learning"*

The design leverages the LLM's semantic understanding rather than adding a preprocessing spell-correction layer, keeping the pipeline simple.

---

### 4. Non-English Input

**Problem:** Users may query in languages other than English.

| Input | Language | Outcome |
|---|---|---|
| `"熱門 python 專案"` | Traditional Chinese | ✅ → `sort=stars, language=python` |
| `"機器學習 repos"` | Traditional Chinese | ✅ → `keywords=["machine learning"]` |
| `"top Python 專案 最新"` | Mixed (EN + ZH) | ✅ → conflict resolved: `sort=updated, min_stars=100` |
| `"人気のPythonリポジトリ"` | Japanese | ✅ → `sort=stars, language=python` |
| `"最新のPythonリポジトリ"` | Japanese | ✅ → `sort=updated, language=python` |

GPT-4o-mini handles Chinese and Japanese well because it was trained on multilingual data and the structured output contract (JSON schema) is language-agnostic. The model translates the *intent* rather than the literal words.

---

### Remaining Failure Cases — Why They Are Fundamentally Hard

#### 1. Conflict rule over-firing on single signals

**Observed:** Input `"top pyhton repos"` (no actual conflict) caused the model to set `min_stars=100`. The conflict resolution prompt describes `"top"` as a signal that may need a popularity floor, and the model applies this even without a competing signal.

**Why it's hard:** The rule "if `top` loses the sort battle, set `min_stars=100`" requires the model to first determine *whether a battle occurred*. Disambiguating "top as the sole intent" from "top as the losing signal in a conflict" depends on counting and reasoning about signals — a task that is straightforward for humans but inconsistent for LLMs without explicit chain-of-thought. Adding a stricter rule (e.g., "only apply the floor if another sort signal is present") could reduce false positives, but requires the model to reliably recognize what constitutes a "competing signal" — itself an ambiguous concept.

#### 2. Keyword typos requiring domain knowledge

**Observed:** `"machien learning"` was initially not normalized. While a direct instruction fixes this specific case, more obscure typos (`"nueral netowrk"`, `"compter vison"`) cannot all be enumerated.

**Why it's hard:** Spell correction is a fundamentally probabilistic problem. "wev framework" could mean "web framework" or "wav framework" (audio). Without domain-specific context, correction requires ranking candidate corrections by likelihood — which is exactly what a statistical spell-checker does. Delegating this to the LLM works for common phrases but is unreliable for long-tail technical terms. A proper fix would require integrating a domain-specific spell-checker or embedding similarity lookup, adding significant complexity.

#### 3. Fully nonsensical input

**Observed:** `"asdfgh python qwer"` produces a sensible result by accident (extracts `language=python`). But `"random stuff pls"` with no language produces a fallback `stars:>0` query — technically valid but not useful.

**Why it's hard:** There is no reliable way to distinguish "a vague query the user genuinely wants answered" from "accidental input". A refusal strategy ("I don't understand this query") would be wrong for `"cool projects"` which is genuinely answerable. The current behavior (return something safe) is the correct tradeoff: it's always better to return a degraded result than to crash or refuse.

---

## Part 2: Multi-Model Evaluation

### Evaluation Design

**30 test cases** across 6 categories, each with manually-labeled ground truth:

| Category | Count | Focus |
|---|---|---|
| `basic` | 9 | Standard queries, language + sort + limit |
| `ambiguous` | 3 | Vague adjectives, no structural signals |
| `typo` | 6 | Language, sort, keyword, limit misspellings |
| `conflict` | 4 | Multiple competing sort signals |
| `multilingual` | 7 | Chinese and Japanese input |
| `fallback` | 1 | Completely uninterpretable input |

Test cases were designed adversarially: conflict cases require understanding the priority order (`updated > stars > forks`) and the `min_stars=100` soft constraint rule; multilingual cases require semantic translation not literal lookup; typo cases include compound errors like `"i want bst pyhton repo latset plz"` where multiple errors overlap.

Ground truth was written manually against the schema specification, not generated or reverse-engineered from model outputs.

### Running the Evaluation

```bash
# Run all 3 models (requires OPENAI_API_KEY + GROQ_API_KEY)
python eval_pipeline.py

# Run one model only
python eval_pipeline.py --model gpt-4o-mini
python eval_pipeline.py --model llama-3.3-70b-versatile
python eval_pipeline.py --model llama-3.1-8b-instant

# Save detailed results
python eval_pipeline.py --save results.json

# Debug individual case failures
$env:DEBUG="1"; python eval_pipeline.py --model gpt-4o-mini
```

---

### Model Selection

Three models were selected to represent a closed-source baseline, a large open-weight model, and a small open-weight model — creating a meaningful capability spread:

| Model | Type | Parameters | Provider | API Key |
|---|---|---|---|---|
| `gpt-4o-mini` | Closed-source | — | OpenAI | `OPENAI_API_KEY` |
| `llama-3.3-70b-versatile` | Open-weight (Meta) | 70B | Groq | `GROQ_API_KEY` |
| `llama-3.1-8b-instant` | Open-weight (Meta) | 8B | Groq | `GROQ_API_KEY` |

**GPT-4o-mini** is the closed-source baseline. It was already integrated into the main CLI, supports native JSON mode (`response_format={"type": "json_object"}`), and has strong instruction-following at low cost. It serves as the reference point for what a well-prompted closed model can do.

**LLaMA 3.3 70B** represents the best available open-weight model. At 70B parameters it is competitive with frontier closed models on structured reasoning tasks. Groq exposes it through an OpenAI-compatible API, so it required no new SDK. The hypothesis was that a sufficiently large open-weight model with the same prompt should match or exceed the closed-source baseline.

**LLaMA 3.1 8B** represents a practical, deployable open-weight model. At 8B parameters it can run on consumer hardware, but the reduced capacity means it struggles with multi-step reasoning tasks — exactly the conflict resolution and multilingual cases in this test set. Including it tests whether the threshold is achievable without frontier-scale compute.

All three models support JSON mode or respond consistently to explicit JSON-only prompting, which is a hard prerequisite for exact-match evaluation.

---

### Performance Results

| Model | Overall | basic | ambiguous | typo | conflict | multilingual | fallback | Threshold |
|---|---|---|---|---|---|---|---|---|
| `gpt-4o-mini` | **90.00%** (27/30) | 7/9 (78%) | 3/3 (100%) | 5/6 (83%) | 4/4 (100%) | 7/7 (100%) | 1/1 (100%) | ✅ >85% |
| `llama-3.3-70b-versatile` | **93.33%** (28/30) | 9/9 (100%) | 3/3 (100%) | 5/6 (83%) | 3/4 (75%) | 7/7 (100%) | 1/1 (100%) | ✅ >85% |
| `llama-3.1-8b-instant` | **83.33%** (25/30) | 9/9 (100%) | 2/3 (67%) | 5/6 (83%) | 2/4 (50%) | 7/7 (100%) | 0/1 (0%) | ❌ <85% |

#### Per-model failure breakdown

**GPT-4o-mini (90%, 3 failures)** — the conflict rule **over-fires** on single-signal inputs:

| Case | Input | Expected `min_stars` | Got | Root cause |
|---|---|---|---|---|
| case_008 | `"top backend repos"` | `null` | `100` | "top" alone triggers the floor; no competing signal present |
| case_009 | `"top 10 web framework projects"` | `null` | `100` | Same: "top" is the only ranking signal |
| case_014 | `"latset python repos"` | `null` | `100` | Typo of "latest" — model imagined a hidden "top" and fired the floor |

All 3 failures are `min_stars` false positives. Notably GPT-4o-mini passed every conflict case (4/4) and every multilingual case (7/7) — it was over-calibrated to the harder cases at the cost of easy ones.

---

**LLaMA 3.3 70B (93.33%, 2 failures)** — the conflict rule **under-fires** on masked or implicit conflicts:

| Case | Input | Expected `min_stars` | Got | Root cause |
|---|---|---|---|---|
| case_017 | `"i want bst pyhton repo latset plz"` | `100` | `null` | Typo-masked "bst" (= "best") not recognized as a popularity signal — floor not applied |
| case_022 | `"popular backend repos sorted by latest"` | `100` | `null` | "sorted by" override correctly sets `sort=updated`, but the losing "popular" floor is dropped |

Both failures are `min_stars` false negatives. The model handles the primary sort correctly in both cases; it simply drops the secondary consequence (setting the floor for the losing signal).

---

**LLaMA 3.1 8B (83.33%, 5 failures)** — same under-fire pattern as 70B, plus 3 additional failures:

| Case | Input | Expected | Got | Root cause |
|---|---|---|---|---|
| case_010 | `"cool python repos"` | `language=python, keywords=[]` | `language=null, keywords=["python"]` | Language misclassified as keyword when preceded by a stop-word |
| case_017 | `"i want bst pyhton repo latset plz"` | `min_stars=100` | `null` | Same as 70B failure |
| case_021 | `"I want top repos but also the most recent ones"` | `min_stars=100` | `null` | Conflict resolved correctly (sort=updated) but floor rule dropped |
| case_022 | `"popular backend repos sorted by latest"` | `min_stars=100` | `null` | Same as 70B failure |
| case_030 | `"random stuff pls"` | `keywords=[]` | `keywords=["random"]` | "random" treated as a domain keyword |

---

#### Cross-model failure analysis

Comparing failures across all three models reveals a clear structure:

| Case | GPT-4o-mini | LLaMA 3.3 70B | LLaMA 3.1 8B | Pattern |
|---|---|---|---|---|
| case_008 | ❌ | ✅ | ✅ | GPT over-fires (no conflict, floor applied) |
| case_009 | ❌ | ✅ | ✅ | GPT over-fires |
| case_014 | ❌ | ✅ | ✅ | GPT over-fires on typo |
| case_017 | ✅ | ❌ | ❌ | All open-weight models under-fire (typo-masked "bst") |
| case_021 | ✅ | ✅ | ❌ | Only 8B under-fires |
| case_022 | ✅ | ❌ | ❌ | 70B and 8B under-fire on implicit "popular" |

**case_017 is the hardest case in the entire set** — the only one failed by two models. The input `"i want bst pyhton repo latset plz"` requires recognizing `"bst"` as a typo of `"best"` (a popularity signal), then applying the soft constraint because `"latset"` (= "latest") wins the sort. That is three sequential steps, each requiring non-obvious inference, all on a heavily noisy input. GPT-4o-mini passed it; both Llama models did not.

**GPT-4o-mini and the Llama models fail on opposite sides of the same rule:**

| Model family | Failure mode | Cause |
|---|---|---|
| GPT-4o-mini | Applies `min_stars=100` when **no conflict exists** | Over-learned the conflict rule |
| LLaMA (70B + 8B) | Skips `min_stars=100` when a conflict **does exist** | Drops the secondary consequence after committing to the primary sort |

Both traces to the same fundamental difficulty: the `min_stars=100` floor rule requires reasoning about a *counterfactual* — "which signal was present but lost?" — rather than a direct mapping from input to output. GPT-4o-mini resolves this by assuming a conflict is always present when it sees "top"; LLaMA models resolve the conflict correctly but fail to remember that the loser needs a consolation constraint.

#### Why LLaMA 3.1 8B couldn't reach 85%

The 8B model shares the exact same 2 failures as LLaMA 3.3 70B (cases 017 and 022), plus 3 additional ones (010, 021, 030). The gap comes from general instruction-following depth: case_010 requires understanding that a language name after a stop-word is still a `language` field (not a keyword), and case_021 requires chaining conflict detection with the floor rule across a natural-language "but also" phrasing.

Attempts made to push it above 85%:
- Adding an explicit conflict few-shot example showing `min_stars=100` being set → improved cases 019 and 020 but did not flip 021 and 022
- Simplifying the conflict resolution section into a numbered checklist → no measurable change

The remaining 2-case gap (83% → 85%) is a capacity constraint. The 8B model applies each individual rule correctly in isolation; it fails when 3+ rules must be chained on noisy input. Fine-tuning on conflict examples, or chain-of-thought prompting that explicitly walks through each step, would be the most reliable paths to closing it.

---

### Learnings

#### On prompt engineering for structured output

**System prompt structure matters more than content volume.** The initial prompt was a flat list of rules that had grown organically with each edge case discovered. Reorganizing it by GitHub API parameter (`q` → `sort` → `order` → `limit` → conflict resolution) — mirroring the structure of the API docs — improved consistency across all models, especially the smaller one. Models follow structure, not just rules.

**Few-shot examples are more reliable than instructions for edge cases.** Adding a single worked example for `"(top1) cool awesome python web framework"` taught the model all three rules (stop-word filtering, language exclusion from keywords, glued-format limit parsing) at once. A written instruction for the same rules alone was less reliable. The model learns patterns from examples faster than from specifications.

**Conflict resolution requires explicit priority, not just enumeration.** Listing three sort signals without stating a winner caused models to pick arbitrarily. Explicitly writing `updated > stars > forks` as a total order made the behavior deterministic. The `min_stars=100` soft constraint for the losing "top" signal was the single hardest rule to prompt reliably — it requires the model to understand what *didn't* win, which is a negation reasoning step.

#### On eval design

**Exact match is strict but correct for structured API outputs.** Partial credit would hide real functional failures: a `sort` value of `"updated"` vs `"stars"` returns completely different GitHub results. Semantic similarity metrics are inappropriate when the output drives downstream API behavior.

**Eval infrastructure bugs are silent and catastrophic.** The first pipeline run returned 0% accuracy. The model outputs were correct; the comparison function had a subtle bug: `dict.get("keywords", [])` returns `None` — not `[]` — when the key exists with a `null` value. A single missed normalization edge case made every case look wrong. The lesson: always print raw model output for 2–3 cases before trusting aggregate numbers.

**Ground truth must be written before seeing model outputs.** Writing expected outputs after observing what models produce leads to anchoring — you unconsciously write ground truth that matches the model's behavior rather than the intended specification. All 30 cases here were written against the schema spec independently of any model run.

#### On building ground truth for structured outputs

The hardest cases to label were the **conflict cases** and their `min_stars=100` rule. There is no objectively correct answer for `"top repos but show newest"` — the popularity floor is a *design decision*, not a factual truth. This means the ground truth encodes the system's policy, not universal correctness. When a model misses this, it is not "wrong" in an absolute sense — it implements a different, equally defensible policy.

This insight generalizes: **for systems that translate intent into structured queries, ground truth defines the system's contract, not objective truth. Accuracy is only meaningful relative to that contract.** Before running any eval, the most important step is writing down the policy decisions your system makes — and being precise enough that a model could follow them as rules.
