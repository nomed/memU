# Tutorial: Build an AI Research Assistant with Persistent Memory

> **Document type:** Tutorial — a learning-oriented, step-by-step guide.

In this tutorial you will build a **command-line AI research assistant** that remembers research notes across sessions, answers questions using that accumulated knowledge, and demonstrates how memory grows richer as you add more material.

By the end you will understand how to:
- Initialize memU with SQLite for durable persistence
- Ingest multiple research notes as separate memory operations
- Retrieve relevant context and inject it into an LLM prompt
- Restart the service and confirm that memory survives the restart

**Time to complete:** 20–30 minutes  
**Difficulty:** Beginner / Intermediate

---

## What you will build

```
research-assistant/
├── assistant.py          # Main script: ingest + query loop
└── memory.db             # SQLite database (created on first run)
```

The assistant:
1. Accepts plain-text research notes (provided inline for this tutorial)
2. Memorizes each note under a user profile
3. Answers questions by retrieving the most relevant stored facts
4. Persists memory in a local SQLite file so facts survive restarts

---

## Prerequisites

| Requirement | Version / Notes |
|---|---|
| Python | 3.13+ |
| memu | `pip install memu` or `uv add memu` |
| OpenAI API key | Set as `OPENAI_API_KEY` environment variable |
| SQLite | Included with Python — no extra install needed |

```bash
pip install memu
export OPENAI_API_KEY=sk-...
```

---

## Step 1: Project setup

Create the project directory and a single script file:

```bash
mkdir research-assistant
cd research-assistant
touch assistant.py
```

Your working directory for this tutorial will be `research-assistant/`.

---

## Step 2: Initialize the memory service with SQLite

Open `assistant.py` and add the service initialization:

```python
"""
AI Research Assistant — tutorial script.

Usage:
    export OPENAI_API_KEY=sk-...
    python assistant.py
"""

import asyncio
import json
import os
import tempfile

from memu.app import MemoryService

# --- Configuration ---
RESEARCHER_ID = "researcher_1"
DB_PATH = "./memory.db"

def create_service() -> MemoryService:
    """Return a MemoryService backed by a local SQLite database."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

    return MemoryService(
        llm_profiles={
            "default": {
                "api_key": api_key,
                "chat_model": "gpt-4o-mini",
            },
        },
        database_config={
            "metadata_store": {
                "provider": "sqlite",
                "dsn": f"sqlite:///{DB_PATH}",
            },
        },
        memorize_config={
            "memory_categories": [
                {"name": "knowledge",    "description": "Research findings and learned concepts"},
                {"name": "goals",        "description": "Research goals and open questions"},
                {"name": "preferences",  "description": "Methodological preferences and constraints"},
            ],
        },
    )
```

**What this does:**

- `database_config` points memU at a local `memory.db` file. On first run, memU creates the schema automatically.
- `memorize_config` seeds three custom categories relevant to research. memU will map extracted facts into these categories.
- The `RESEARCHER_ID` will scope all memory to one logical user; see [howto-user-scoped-memory.md](howto-user-scoped-memory.md) for multi-user patterns.

---

## Step 3: Ingest research notes

Add a function that accepts a note as a plain string, writes it to a temporary file, and calls `memorize()`:

```python
async def ingest_note(service: MemoryService, note_text: str, label: str) -> None:
    """Memorize a research note under the researcher's user scope."""
    # memU expects conversation/document resources as files.
    # We write the note to a temp file and clean it up after ingestion.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(note_text)
        tmp_path = f.name

    try:
        result = await service.memorize(
            resource_url=tmp_path,
            modality="document",
            user={"user_id": RESEARCHER_ID},
        )
        item_count = len(result.get("items", []))
        cat_names  = [c["name"] for c in result.get("categories", [])]
        print(f"  ✓ '{label}': {item_count} items → categories {cat_names}")
    finally:
        os.unlink(tmp_path)
```

Now add the first batch of research notes:

```python
INITIAL_NOTES = [
    (
        "transformer-attention",
        """
        Transformers use scaled dot-product attention to weigh token relationships.
        The attention formula is: Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V
        Key insight: multi-head attention lets the model attend to different
        representation subspaces simultaneously.
        First introduced in 'Attention Is All You Need' (Vaswani et al., 2017).
        """,
    ),
    (
        "rag-overview",
        """
        Retrieval-Augmented Generation (RAG) combines a retrieval system with a generative LLM.
        The retrieval component fetches relevant documents from an external store.
        The generator conditions on both the query and the retrieved documents.
        RAG reduces hallucinations on knowledge-intensive tasks compared to pure generation.
        Introduced by Lewis et al. (2020), 'Retrieval-Augmented Generation for NLP'.
        """,
    ),
    (
        "vector-databases",
        """
        Vector databases store embeddings and support approximate nearest-neighbour (ANN) search.
        Common choices: pgvector (Postgres extension), Chroma, Weaviate, Pinecone.
        ANN algorithms include HNSW and IVF-Flat, which trade recall for speed.
        For small corpora (< 100k items), brute-force cosine search is often fast enough.
        """,
    ),
]
```

---

## Step 4: Query the assistant

Add a retrieval and prompt-building function:

```python
async def ask(service: MemoryService, question: str) -> str:
    """Retrieve relevant memories and format them as a research context string."""
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": question}}],
        where={"user_id": RESEARCHER_ID},
        method="rag",
    )

    items = result.get("items", [])
    categories = result.get("categories", [])

    if not items and not categories:
        return "(No relevant memories found. Try ingesting more notes first.)"

    lines = ["## Retrieved research context\n"]

    if categories:
        lines.append("### Category summaries")
        for cat in categories:
            name    = cat.get("name", "unknown")
            summary = cat.get("summary") or cat.get("description") or ""
            if summary:
                lines.append(f"**{name}:** {summary}")
        lines.append("")

    if items:
        lines.append("### Memory items")
        for item in items:
            summary = item.get("summary", "")
            if summary:
                lines.append(f"- {summary}")

    return "\n".join(lines)
```

---

## Step 5: First run — ingest notes and query

Add the `main()` function and entry point:

```python
async def main() -> None:
    print("=== AI Research Assistant ===\n")
    service = create_service()

    # --- Ingest initial research notes ---
    print("Ingesting initial research notes...")
    for label, note in INITIAL_NOTES:
        await ingest_note(service, note, label)
    print()

    # --- Query the assistant ---
    questions = [
        "What is the attention mechanism in transformers?",
        "How does RAG reduce hallucinations?",
        "When should I use brute-force vector search instead of ANN?",
    ]

    for question in questions:
        print(f"Q: {question}")
        context = await ask(service, question)
        print(context)
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

Run the script:

```bash
python assistant.py
```

Expected output (abbreviated):

```
=== AI Research Assistant ===

Ingesting initial research notes...
  ✓ 'transformer-attention': 4 items → categories ['knowledge']
  ✓ 'rag-overview': 3 items → categories ['knowledge', 'goals']
  ✓ 'vector-databases': 4 items → categories ['knowledge']

Q: What is the attention mechanism in transformers?
## Retrieved research context

### Memory items
- Transformers use scaled dot-product attention to weigh token relationships.
- Multi-head attention lets the model attend to different representation subspaces simultaneously.
- ...
```

---

## Step 6: Add more notes and observe memory growth

Add a second batch of notes and run a follow-up query to see how memory grows:

```python
ADDITIONAL_NOTES = [
    (
        "fine-tuning-vs-rag",
        """
        Fine-tuning updates model weights and encodes knowledge statically.
        RAG retrieves knowledge dynamically at inference time.
        Fine-tuning is better for style/format adaptation; RAG is better for
        factual recall over a large, frequently updated knowledge base.
        Combining both (fine-tuned retriever + fine-tuned generator) is an active research area.
        """,
    ),
    (
        "embedding-models",
        """
        Embedding models convert text into dense float vectors.
        OpenAI's text-embedding-3-small is cost-effective for most RAG workloads.
        Sentence-transformers (all-MiniLM, bge-m3) are strong open-source alternatives.
        Embedding dimensionality affects both retrieval quality and storage cost.
        Larger dimensions (1536+) typically improve recall for complex queries.
        """,
    ),
]
```

Modify `main()` to ingest the second batch after the first query loop:

```python
    # --- Add more notes ---
    print("\nAdding more research notes...")
    for label, note in ADDITIONAL_NOTES:
        await ingest_note(service, note, label)
    print()

    # --- Query with enriched memory ---
    follow_up_questions = [
        "When should I choose fine-tuning over RAG?",
        "What embedding model should I use for a large knowledge base?",
    ]

    print("Follow-up queries (memory now includes 5 notes):")
    for question in follow_up_questions:
        print(f"\nQ: {question}")
        context = await ask(service, question)
        print(context)
        print("-" * 60)
```

Each new `memorize()` call updates the category summaries for `knowledge` — the assistant's answers become richer without the queries changing.

---

## Step 7: Persist across sessions

SQLite stores all data in `memory.db`. To verify persistence, exit Python and restart:

```python
# In a fresh Python session (or a new script):

import asyncio
from memu.app import MemoryService
import os

async def verify_persistence() -> None:
    service = MemoryService(
        llm_profiles={
            "default": {
                "api_key": os.environ["OPENAI_API_KEY"],
                "chat_model": "gpt-4o-mini",
            },
        },
        database_config={
            "metadata_store": {
                "provider": "sqlite",
                "dsn": "sqlite:///./memory.db",   # same file as before
            },
        },
    )

    # Retrieve without ingesting anything new
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": "What do I know about transformers?"}}],
        where={"user_id": "researcher_1"},
        method="rag",
    )

    items = result.get("items", [])
    print(f"Items retrieved from persistent store: {len(items)}")
    for item in items:
        print(f"  - {item.get('summary', '')}")

asyncio.run(verify_persistence())
```

Run this in a new terminal (without re-running `main()`). You should see the items extracted in the previous session returned immediately, confirming that SQLite durability is working correctly.

---

## Complete script

The full `assistant.py` is assembled from the steps above. Here it is in one place for easy copy-paste:

```python
"""
AI Research Assistant — tutorial script.

Usage:
    export OPENAI_API_KEY=sk-...
    python assistant.py
"""

import asyncio
import os
import tempfile

from memu.app import MemoryService

RESEARCHER_ID = "researcher_1"
DB_PATH = "./memory.db"


def create_service() -> MemoryService:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    return MemoryService(
        llm_profiles={"default": {"api_key": api_key, "chat_model": "gpt-4o-mini"}},
        database_config={
            "metadata_store": {"provider": "sqlite", "dsn": f"sqlite:///{DB_PATH}"},
        },
        memorize_config={
            "memory_categories": [
                {"name": "knowledge",   "description": "Research findings and learned concepts"},
                {"name": "goals",       "description": "Research goals and open questions"},
                {"name": "preferences", "description": "Methodological preferences and constraints"},
            ],
        },
    )


async def ingest_note(service: MemoryService, note_text: str, label: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(note_text)
        tmp_path = f.name
    try:
        result = await service.memorize(
            resource_url=tmp_path,
            modality="document",
            user={"user_id": RESEARCHER_ID},
        )
        item_count = len(result.get("items", []))
        cat_names  = [c["name"] for c in result.get("categories", [])]
        print(f"  ✓ '{label}': {item_count} items → categories {cat_names}")
    finally:
        os.unlink(tmp_path)


async def ask(service: MemoryService, question: str) -> str:
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": question}}],
        where={"user_id": RESEARCHER_ID},
        method="rag",
    )
    items      = result.get("items", [])
    categories = result.get("categories", [])

    if not items and not categories:
        return "(No relevant memories found.)"

    lines = ["## Retrieved research context\n"]
    if categories:
        lines.append("### Category summaries")
        for cat in categories:
            name    = cat.get("name", "unknown")
            summary = cat.get("summary") or cat.get("description") or ""
            if summary:
                lines.append(f"**{name}:** {summary}")
        lines.append("")
    if items:
        lines.append("### Memory items")
        for item in items:
            summary = item.get("summary", "")
            if summary:
                lines.append(f"- {summary}")
    return "\n".join(lines)


INITIAL_NOTES = [
    (
        "transformer-attention",
        (
            "Transformers use scaled dot-product attention to weigh token relationships.\n"
            "Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V\n"
            "Multi-head attention lets the model attend to different representation subspaces simultaneously.\n"
            "First introduced in 'Attention Is All You Need' (Vaswani et al., 2017)."
        ),
    ),
    (
        "rag-overview",
        (
            "Retrieval-Augmented Generation (RAG) combines a retrieval system with a generative LLM.\n"
            "The retrieval component fetches relevant documents from an external store.\n"
            "RAG reduces hallucinations on knowledge-intensive tasks.\n"
            "Introduced by Lewis et al. (2020)."
        ),
    ),
    (
        "vector-databases",
        (
            "Vector databases store embeddings and support approximate nearest-neighbour (ANN) search.\n"
            "Common choices: pgvector, Chroma, Weaviate, Pinecone.\n"
            "For small corpora (< 100k items), brute-force cosine search is often fast enough."
        ),
    ),
]

ADDITIONAL_NOTES = [
    (
        "fine-tuning-vs-rag",
        (
            "Fine-tuning updates model weights and encodes knowledge statically.\n"
            "RAG retrieves knowledge dynamically at inference time.\n"
            "RAG is better for factual recall over a large, frequently updated knowledge base."
        ),
    ),
    (
        "embedding-models",
        (
            "OpenAI's text-embedding-3-small is cost-effective for most RAG workloads.\n"
            "Larger dimensions (1536+) typically improve recall for complex queries.\n"
            "Sentence-transformers are strong open-source alternatives."
        ),
    ),
]


async def main() -> None:
    print("=== AI Research Assistant ===\n")
    service = create_service()

    print("Ingesting initial research notes...")
    for label, note in INITIAL_NOTES:
        await ingest_note(service, note, label)

    print("\nInitial queries:")
    for q in [
        "What is the attention mechanism in transformers?",
        "How does RAG reduce hallucinations?",
    ]:
        print(f"\nQ: {q}")
        print(await ask(service, q))
        print("-" * 60)

    print("\nAdding more research notes...")
    for label, note in ADDITIONAL_NOTES:
        await ingest_note(service, note, label)

    print("\nFollow-up queries (enriched memory):")
    for q in [
        "When should I choose fine-tuning over RAG?",
        "What embedding model should I use?",
    ]:
        print(f"\nQ: {q}")
        print(await ask(service, q))
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## What you have learned

| Concept | Where you used it |
|---|---|
| `MemoryService` initialization with SQLite | `create_service()` |
| `memorize()` with `modality="document"` | `ingest_note()` |
| `retrieve()` with user scoping and `method="rag"` | `ask()` |
| Incremental memory growth (multiple ingestion calls) | `ADDITIONAL_NOTES` batch |
| Persistence across process restarts | Step 7 verification script |
| Custom memory categories | `memorize_config` in `create_service()` |

---

## Next steps

- **Switch to Postgres** for multi-user or concurrent access: see [howto-persistent-storage.md](howto-persistent-storage.md).
- **Add user scoping** to support multiple researchers with isolated memory: see [howto-user-scoped-memory.md](howto-user-scoped-memory.md).
- **Use `method="llm"` retrieval** for nuanced reasoning queries where embedding similarity is insufficient.
- **Explore LangGraph integration** to embed this memory layer into an agent graph: see [`docs/langgraph_integration.md`](../docs/langgraph_integration.md).
- **Tune retrieval** with `retrieve_config` options (`top_k`, `ranking`, `sufficiency_check`) for your domain.
