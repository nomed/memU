# `memorize_config` — Reference and Recommendations

> **Document type:** Reference + How-to
>
> This page answers two questions at once:
> - _What does every `memorize_config` field do?_
> - _What configuration does memU recommend for common scenarios?_

---

## What is `memorize_config`?

`memorize_config` is the single configuration object that controls **what** memU memorizes and
**how** it organises that information.  It is passed to `MemoryService` at construction time and
drives three stages of the `memorize` pipeline:

| Pipeline stage | `memorize_config` fields involved |
|---|---|
| **Preprocess** (`preprocess_multimodal`) | `preprocess_llm_profile`, `multimodal_preprocess_prompts` |
| **Extract** (`extract_items`) | `memory_types`, `memory_type_prompts`, `memory_extract_llm_profile` |
| **Categorise & persist** (`categorize_items`, `persist_index`) | `memory_categories`, `default_category_summary_prompt`, `default_category_summary_target_length`, `category_update_llm_profile`, `enable_item_references`, `enable_item_reinforcement` |

It can be passed as a dict or a `MemorizeConfig` instance:

```python
from memu.app import MemoryService, MemorizeConfig

service = MemoryService(
    memorize_config={
        "memory_types": ["profile", "event", "knowledge"],
        "memory_categories": [
            {"name": "facts",       "description": "Verified facts about the user"},
            {"name": "preferences", "description": "User preferences and tastes"},
        ],
    },
)
```

---

## Field reference

### `memory_types`

```python
memory_types: list[str] = ["profile", "event"]
```

Controls which **memory type extractors** run against each ingested resource.
Each type uses a distinct LLM prompt optimised for a different kind of information.

| Type | What it captures |
|---|---|
| `profile` | Stable personal attributes — name, job, location, preferences |
| `event` | Specific occurrences at a point in time — activities, meetings, experiences |
| `knowledge` | Facts, domain knowledge, information the user has learned or shared |
| `behavior` | Recurring behavioural patterns and habits |
| `skill` | Skills, competencies, and expertise areas |
| `tool` | Software tools, services, and technical stack items |

> **Recommendation:** Start with the default `["profile", "event"]`.  Add `"knowledge"` if
> you store documents or research notes.  Add `"behavior"` for proactive assistant scenarios.
> Adding all six types increases LLM cost roughly linearly.

---

### `memory_categories`

```python
memory_categories: list[CategoryConfig] = [<10 default categories>]
```

Defines the **category taxonomy** used to organise memory items.  Each item is assigned to
one or more categories at extraction time.  Categories accumulate running summaries that are
updated on every `memorize()` call.

The 10 built-in defaults are:

| Name | Description |
|---|---|
| `personal_info` | Personal information about the user |
| `preferences` | User preferences, likes and dislikes |
| `relationships` | Information about relationships with others |
| `activities` | Activities, hobbies, and interests |
| `goals` | Goals, aspirations, and objectives |
| `experiences` | Past experiences and events |
| `knowledge` | Knowledge, facts, and learned information |
| `opinions` | Opinions, viewpoints, and perspectives |
| `habits` | Habits, routines, and patterns |
| `work_life` | Work-related information and professional life |

#### `CategoryConfig` fields

```python
class CategoryConfig(BaseModel):
    name: str                                  # required; used as the category id
    description: str = ""                      # shown to the LLM during extraction
    target_length: int | None = None           # override default_category_summary_target_length
    summary_prompt: str | CustomPrompt | None = None  # override default_category_summary_prompt
```

> **Recommendation:** Replace the 10 defaults with a smaller, focused taxonomy that matches your
> domain.  Three to eight categories work well; fewer categories give richer summaries.
> Descriptions are read by the LLM — write them clearly and specifically.

---

### `default_category_summary_target_length`

```python
default_category_summary_target_length: int = 400
```

Maximum word count for category summaries when the LLM regenerates them.  Individual
categories can override this via `CategoryConfig.target_length`.

> **Recommendation:** Use `400` (default) for most personal-assistant scenarios.  Raise to
> `600`–`800` if categories contain dense technical or factual content.  Lower to `200`–`300`
> if summaries are retrieved verbatim and token budget is a concern.

---

### `default_category_summary_prompt`

```python
default_category_summary_prompt: str | CustomPrompt = <built-in prompt>
```

System prompt used when regenerating a category's running summary.  Override with a plain
string or a `CustomPrompt` block composition.  Individual categories can override this via
`CategoryConfig.summary_prompt`.

Use this field when you need the LLM to adopt a specific tone, language, or format for
all category summaries.

---

### `memory_type_prompts`

```python
memory_type_prompts: dict[str, str | CustomPrompt] = <built-in prompts per type>
```

Per-memory-type prompt overrides.  Keys must match entries in `memory_types`.
Use a plain string to replace the built-in prompt entirely, or a `CustomPrompt` to
replace individual blocks while keeping the rest.

Override example — force `profile` extraction in a specific language:

```python
memorize_config={
    "memory_types": ["profile", "event"],
    "memory_type_prompts": {
        "profile": "Extract user profile facts from the text.  Always write in Italian.  ...",
    },
}
```

---

### `multimodal_preprocess_prompts`

```python
multimodal_preprocess_prompts: dict[str, str | CustomPrompt] = {}
```

Override the **preprocess** system prompt for a specific modality.  Keys must be a valid
modality string (`"conversation"`, `"document"`, `"image"`, `"video"`, `"audio"`).

Most applications do not need this.  Use it when you want the LLM to apply domain-specific
attention (e.g., ignore boilerplate headers in documents, focus on speaker turns in audio).

---

### LLM profile fields

```python
preprocess_llm_profile: str = "default"
memory_extract_llm_profile: str = "default"
category_update_llm_profile: str = "default"
```

Route each pipeline stage to a different named LLM profile from `llm_profiles`.

> **Recommendation:** Use a lightweight model for preprocessing (`preprocess_llm_profile`)
> and category updates (`category_update_llm_profile`), and reserve your most capable model
> for extraction (`memory_extract_llm_profile`).

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o",            # extraction: high quality
        },
        "fast": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o-mini",       # preprocess + summary: cheaper
        },
    },
    memorize_config={
        "preprocess_llm_profile": "fast",
        "memory_extract_llm_profile": "default",
        "category_update_llm_profile": "fast",
    },
)
```

---

### `enable_item_references`

```python
enable_item_references: bool = False
```

When `True`, category summaries include inline `[ref:ITEM_ID]` citations linking each
claim in the summary back to the source memory item that generated it.

> **Recommendation:** Enable when traceability matters — for example, when exposing category
> summaries to users who need to verify or edit specific facts.  Leave disabled for pure
> retrieval use cases where citation overhead is not needed.

---

### `enable_item_reinforcement`

```python
enable_item_reinforcement: bool = False
```

When `True`, memU tracks how many times an equivalent memory item has been seen across
multiple `memorize()` calls (reinforcement counting).  Duplicate items are merged rather
than stored again.

> **Recommendation:** Enable in high-volume or long-running sessions where the same facts
> may appear repeatedly (e.g., a daily journaling assistant).  Disable for document ingestion
> pipelines where every resource is distinct.

---

### `category_assign_threshold`

```python
category_assign_threshold: float = 0.25
```

Minimum semantic similarity score (0–1) required for a memory item to be assigned to a
category via vector search.  Declared for future use; not currently applied in the default
pipeline.

---

## Recommended configurations

### 1. Minimal — zero config (defaults)

No `memorize_config` is needed.  memU extracts `profile` and `event` memories across the
10 built-in categories.

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": os.environ["OPENAI_API_KEY"]}},
)
```

Use this when prototyping or when the built-in taxonomy is a good fit.

---

### 2. Focused personal assistant

Replace the default 10-category taxonomy with a smaller set tuned to your assistant's purpose.
Add `knowledge` and `behavior` types for richer profiling.

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": os.environ["OPENAI_API_KEY"]}},
    memorize_config={
        "memory_types": ["profile", "event", "knowledge", "behavior"],
        "memory_categories": [
            {
                "name": "identity",
                "description": "Basic personal facts: name, age, location, job, family",
            },
            {
                "name": "preferences",
                "description": "Likes, dislikes, tastes in food, music, sports, entertainment",
            },
            {
                "name": "work",
                "description": "Professional context: role, team, projects, tools used",
            },
            {
                "name": "goals",
                "description": "Current goals, aspirations, and things the user is working towards",
            },
            {
                "name": "routines",
                "description": "Regular habits, daily routines, and recurring patterns",
            },
        ],
    },
)
```

---

### 3. Document knowledge base

Ingest research notes, articles, or technical documentation.  Use `knowledge` as the
primary type.  Add a larger `target_length` to capture denser content.

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": os.environ["OPENAI_API_KEY"]}},
    memorize_config={
        "memory_types": ["knowledge"],
        "memory_categories": [
            {"name": "concepts",    "description": "Core concepts, definitions, and terminology"},
            {"name": "findings",    "description": "Key findings, results, and conclusions"},
            {"name": "methods",     "description": "Methods, algorithms, and procedures"},
            {"name": "references",  "description": "Citations, sources, and related work"},
        ],
        "default_category_summary_target_length": 700,
    },
)
```

---

### 4. Cost-optimised — split LLM profiles

Route the two most expensive calls (extraction) to a capable model, and the cheaper
calls (preprocess, summary) to a fast model.

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o",
        },
        "fast": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o-mini",
        },
    },
    memorize_config={
        "preprocess_llm_profile": "fast",
        "memory_extract_llm_profile": "default",
        "category_update_llm_profile": "fast",
    },
)
```

---

### 5. Traceable summaries with item references

Enable `enable_item_references` so that category summaries cite the specific memory
items that contributed to each claim.

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": os.environ["OPENAI_API_KEY"]}},
    memorize_config={
        "memory_types": ["profile", "event"],
        "enable_item_references": True,
        "memory_categories": [
            {"name": "profile",  "description": "Who the user is"},
            {"name": "timeline", "description": "What the user has done and when"},
        ],
    },
)
```

The resulting category summary text will contain inline references like
`[ref:a1b2c3]` that can be matched against the `id` field of returned
`MemoryItem` objects.

---

### 6. High-volume deduplication

Enable `enable_item_reinforcement` when the same information appears across many sessions
and you want memU to track frequency rather than create duplicate items.

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": os.environ["OPENAI_API_KEY"]}},
    memorize_config={
        "enable_item_reinforcement": True,
    },
)
```

---

## Applying per-category overrides

`CategoryConfig.summary_prompt` and `CategoryConfig.target_length` let you diverge from the
global defaults for a single category:

```python
memorize_config={
    "memory_categories": [
        {
            "name": "profile",
            "description": "Stable personal facts",
            "target_length": 200,           # shorter — just the key facts
        },
        {
            "name": "work",
            "description": "Professional context",
            "target_length": 600,           # longer — detailed technical context
            "summary_prompt": (
                "You are a technical profile writer.  "
                "Summarise the user's professional context including their current role, "
                "team, projects, and technology stack.  Be precise and use bullet points.  "
                "Max {target_length} words."
            ),
        },
    ],
}
```

---

## What `memorize_config` does NOT control

The following are configured elsewhere:

| Concern | Configured via |
|---|---|
| Storage backend (SQLite, Postgres, in-memory) | `database_config` |
| Vector index type | `database_config.vector_index` |
| Retrieval behaviour (RAG vs LLM, top-k, …) | `retrieve_config` |
| LLM models and API keys | `llm_profiles` |
| User scope isolation | `user_config` / `where` parameter on `memorize()` |
| Blob storage directory | `blob_config` |
