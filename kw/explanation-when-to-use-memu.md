# When to Use memU — Explanation

> **Document type:** Explanation — concepts, trade-offs, and decision guidance.

---

## The problem memU solves

Large-language models are stateless by design. Every new API call starts with a blank slate: the model does not remember the user's name from yesterday, the preference mentioned last week, or the goal set three conversations ago. The only "memory" available is what you pack into the current context window, which is finite, expensive to fill, and lost when the session ends.

memU solves this by providing a **persistent, structured memory layer** that lives outside the model. Conversations, documents, and other inputs are processed into atomic memory items, organised into categories, and stored in a database. Future interactions can retrieve the most relevant items and inject them back into the model's context — giving the agent a growing, queryable record of what it knows about each user.

---

## Core mental model: memory as a file system

memU organises memory in three nested layers, modelled after a file system:

| Layer | Analogy | What it stores |
|---|---|---|
| `Resource` | File | The raw source artifact: a conversation transcript, a document, an audio clip |
| `MemoryItem` | Line in a file | A single extracted fact, preference, goal, or event — with an embedding vector |
| `MemoryCategory` | Folder | A topic summary that groups related items (e.g. `preferences`, `goals`) |

When you call `memorize()`, memU walks from Resource → MemoryItem → MemoryCategory, extracting and organising knowledge from the source. When you call `retrieve()`, it walks in the opposite direction: it finds the most relevant categories, then items, then optionally the originating resources, and returns the results for you to inject into a prompt.

This hierarchy means you can ask broad questions ("what do I know about Alice's work life?") or narrow ones ("what are Alice's top-ranked items about project deadlines?"), and the retrieval pipeline handles the scoping.

---

## When to use memU

### Conversational assistants with repeat users

Any chatbot or voice assistant that talks to the same user across multiple sessions benefits from persistent memory. memU memorizes each conversation turn, so the next session can open with "you mentioned last week that you prefer concise answers — keeping that in mind." The assistant grows smarter with each interaction without re-reading entire history.

### long-running autonomous agents

Agents that run over days or weeks — research bots, project managers, personal productivity agents — need to remember what they have already done, what they discovered, and what remains. memU gives these agents a structured journal: past resources (documents, search results) are stored, and the agent can retrieve context-specific items before taking the next action.

### Multi-user SaaS applications

When your product serves thousands of users, each must have isolated memory. memU's `user_config` system lets you attach arbitrary scope fields (`user_id`, `agent_id`, etc.) to every memory record. Retrieval queries are validated against those fields, so Alice's memories never leak into Bob's context. See [howto-user-scoped-memory.md](howto-user-scoped-memory.md) for implementation details.

### Skill and preference extraction from logs

If you have a corpus of historical chat logs, support tickets, or document interactions, memU can batch-ingest them and build a rich profile: what topics the user knows well (`knowledge` category), what they asked for repeatedly (`habits`), and what outcomes they care about (`goals`). The structured output is immediately queryable by downstream agents.

### Proactive agents

An agent that needs to surface relevant context without waiting for a user to ask — "you have a meeting tomorrow with Bob; here is what you know about him" — relies on proactive retrieval. memU's `retrieve()` call can be triggered on any input (a calendar event, a new document, a cron schedule) to surface what is known about the entities involved.

---

## When NOT to use memU

### Pure stateless API services

If your service processes each request independently with no need for cross-request context, adding a memory layer introduces unnecessary latency and storage cost. A translation API, a code formatter, or a single-turn Q&A endpoint over a fixed document does not need memU.

### Single-shot queries over a known corpus

If the information your agent needs is already in a fixed, versioned document store (e.g. product documentation, a legal database), a standard RAG pipeline over that corpus is simpler and more predictable. memU is designed for *evolving, user-specific* knowledge, not static reference material.

### Applications with no cross-session state

If each session is inherently independent — a one-off report generator, a batch data processor — the overhead of storing and retrieving memories provides no benefit. memU shines when value accumulates over time.

---

## Storage backend trade-offs

memU ships three pluggable backends. Choose based on your deployment context:

| | `inmemory` | `sqlite` | `postgres` |
|---|---|---|---|
| **Persistence** | None — reset on restart | File-based, durable | Server-based, durable |
| **Setup effort** | Zero | Near-zero (`dsn` path only) | Docker / managed service + `pgvector` |
| **Vector search** | Brute-force | Brute-force (JSON embeddings) | pgvector (ANN index available) |
| **Concurrency** | Single-process only | Single-writer, multi-reader | Full concurrent access |
| **Scale** | Hundreds of items | Thousands of items | Millions of items |
| **Best for** | Tests, prototypes, CI | Single-user apps, small deployments | Production multi-user SaaS |

> **Note:** SQLite and inmemory use brute-force cosine similarity for vector search. This is portable and requires no extensions, but query time scales linearly with item count. For large deployments, migrate to Postgres with pgvector.

---

## Retrieval method trade-offs: `rag` vs `llm`

`retrieve()` supports two strategies, set via `method` in `RetrieveConfig` or per-call:

| | `rag` | `llm` |
|---|---|---|
| **Mechanism** | Embedding similarity (cosine) + optional salience ranking | LLM re-ranks candidates from formatted context |
| **Latency** | Fast — vector math only for ranking | Slower — one or more additional LLM calls |
| **Quality** | Good for factual recall, keyword-rich queries | Better for intent disambiguation and nuanced queries |
| **Cost** | Low (no extra LLM tokens for ranking) | Higher (additional prompt tokens) |
| **Best for** | High-volume retrieval, production defaults | Complex agent reasoning, ambiguous queries |

> **Tip:** Start with `rag` (the default). Switch to `llm` when you observe the agent missing relevant context because the query phrasing does not closely match stored item text.

Both methods share the same staged pipeline (category recall → sufficiency check → item recall → sufficiency check → resource recall) and return identical response shapes: `{categories, items, resources, next_step_query}`.

---

## How user scoping works — and why it matters

By default, memU includes a `user_id` field on every record. You extend this by providing a Pydantic `BaseModel` as `UserConfig.model`:

```python
from pydantic import BaseModel
from memu.app import MemoryService

class UserScope(BaseModel):
    user_id: str | None = None
    agent_id: str | None = None

service = MemoryService(
    llm_profiles={"default": {"api_key": "..."}},
    user_config={"model": UserScope},
)
```

memU merges this model into all four storage tables (resources, items, categories, relations), making scope fields first-class columns. Every `memorize()` call attaches the provided `user` dict to stored records. Every `retrieve()` call validates the `where` dict against the model fields before executing queries — unknown fields raise an error rather than silently returning wrong data.

**Why this matters:** In a multi-user app, failing to scope queries means one user's memories pollute another's context. memU makes isolation structural, not an afterthought — the `where` filter is part of the storage contract, not an optional add-on.

> **Warning:** If you omit `where` in `retrieve()`, the query runs across all records in the database. For single-user apps this is fine. For multi-user apps, always pass `where={"user_id": user_id}`.
