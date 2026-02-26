# How to Scope Memory to Individual Users

> **Document type:** How-to — a task-focused guide for a specific goal.

**Goal:** Configure memU so that each user in a multi-user application has isolated memory, and enforce that isolation at both write and read time.

---

## Prerequisites

- `memu` installed (`pip install memu` or `uv add memu`)
- Familiarity with Pydantic `BaseModel`
- A persistent backend (SQLite or Postgres) for production use

---

## Why user scoping is needed

By default, all memory records share the same database tables. Without scoping, a `retrieve()` call returns the most similar items regardless of which user they belong to. In a multi-user application this means:

- User A could receive memories that belong to User B.
- A privacy boundary that should exist in the data layer is instead delegated to application code, which is error-prone.

memU makes isolation structural. When you declare a scope model, memU merges those fields into all four storage tables as first-class columns. Every `memorize()` call tags records with the provided user data, and every `retrieve()` call validates and applies the `where` filter before querying.

---

## Step 1: Define a UserScope model

Create a Pydantic `BaseModel` with the fields you want to use for scoping. The most common is `user_id`:

```python
from pydantic import BaseModel

class UserScope(BaseModel):
    user_id: str | None = None
```

You can add additional dimensions, such as an `agent_id` for per-agent memory isolation:

```python
class UserScope(BaseModel):
    user_id: str | None = None
    agent_id: str | None = None
```

All fields default to `None` so that queries without a specific scope value remain valid.

---

## Step 2: Pass the scope model to MemoryService

Provide the model class (not an instance) as `UserConfig.model`:

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o-mini",
        },
    },
    user_config={"model": UserScope},
    database_config={
        "metadata_store": {
            "provider": "sqlite",
            "dsn": "sqlite:///./multi_user_memory.db",
        },
    },
)
```

memU reads the model's field names and types at startup and adds them as columns to all tables. This happens automatically — no manual schema migration is needed when `ddl_mode="create"` (the default).

---

## Step 3: Memorize data for a specific user

Pass the user identity as the `user` argument to `memorize()`:

```python
import asyncio
import json
import os
import tempfile

async def ingest_for_user(user_id: str, messages: list[dict]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(messages, f)
        tmp_path = f.name

    try:
        result = await service.memorize(
            resource_url=tmp_path,
            modality="conversation",
            user={"user_id": user_id},
        )
        print(f"[{user_id}] stored {len(result['items'])} items")
    finally:
        os.unlink(tmp_path)

# Ingest for two different users
alice_messages = [
    {"role": "user", "content": "I love hiking and the outdoors."},
    {"role": "assistant", "content": "That sounds great!"},
]
bob_messages = [
    {"role": "user", "content": "I'm a professional chef specializing in Italian cuisine."},
    {"role": "assistant", "content": "Wonderful! Do you have a favourite dish?"},
]

asyncio.run(ingest_for_user("alice", alice_messages))
asyncio.run(ingest_for_user("bob",   bob_messages))
```

Every resource, memory item, category, and relation stored during these calls is tagged with the respective `user_id`.

---

## Step 4: Filter retrieval with `where`

Pass a `where` dict matching your scope model to `retrieve()`:

```python
async def retrieve_for_user(user_id: str, query: str) -> list[dict]:
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": query}}],
        where={"user_id": user_id},
        method="rag",
    )
    return result.get("items", [])

# Alice's retrieval — only returns Alice's memories
alice_items = asyncio.run(retrieve_for_user("alice", "What does this user enjoy?"))

# Bob's retrieval — only returns Bob's memories
bob_items = asyncio.run(retrieve_for_user("bob", "What does this user do professionally?"))
```

memU validates the `where` dict against the declared `UserScope` model before executing the query. Passing an unknown field (e.g. `where={"unknown_field": "x"}`) raises a validation error rather than silently returning wrong data.

---

## Step 5: Understand what happens if `where` is omitted

If you call `retrieve()` without a `where` argument, the query runs across **all records in the database**:

```python
# Without where — returns items from ALL users
result = await service.retrieve(
    queries=[{"role": "user", "content": {"text": "What do users enjoy?"}}],
    # where is omitted
)
```

This is acceptable for:
- Single-user applications where there is only one logical user
- Administrative tooling that intentionally aggregates across users
- Development and testing

> **Warning:** In a multi-user application, always pass `where={"user_id": user_id}` in every `retrieve()` call. Relying on application logic to filter results after the fact is fragile and risks data leakage.

---

## Complete example

```python
"""
Multi-user scoped memory example.

Usage:
    export OPENAI_API_KEY=sk-...
    python user_scoped_memory.py
"""

import asyncio
import json
import os
import tempfile

from pydantic import BaseModel
from memu.app import MemoryService


class UserScope(BaseModel):
    user_id: str | None = None


async def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    service = MemoryService(
        llm_profiles={
            "default": {"api_key": api_key, "chat_model": "gpt-4o-mini"},
        },
        user_config={"model": UserScope},
    )

    # --- Memorize for two users ---
    user_conversations = {
        "alice": [
            {"role": "user",      "content": "I love hiking and being outdoors."},
            {"role": "assistant", "content": "Sounds adventurous!"},
        ],
        "bob": [
            {"role": "user",      "content": "I'm a chef specializing in Italian cuisine."},
            {"role": "assistant", "content": "Wonderful!"},
        ],
    }

    for user_id, messages in user_conversations.items():
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(messages, f)
            tmp_path = f.name
        try:
            result = await service.memorize(
                resource_url=tmp_path,
                modality="conversation",
                user={"user_id": user_id},
            )
            print(f"[{user_id}] memorized {len(result['items'])} items")
        finally:
            os.unlink(tmp_path)

    # --- Retrieve for each user independently ---
    for user_id, query in [
        ("alice", "What outdoor activities does this user enjoy?"),
        ("bob",   "What is this user's profession?"),
    ]:
        result = await service.retrieve(
            queries=[{"role": "user", "content": {"text": query}}],
            where={"user_id": user_id},
            method="rag",
        )
        items = result.get("items", [])
        print(f"\n[{user_id}] query: '{query}'")
        for item in items:
            print(f"  - {item.get('summary')}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary

| Step | What to do |
|---|---|
| Define scope | Create a Pydantic `BaseModel` with `user_id` (and any other scope fields) |
| Register scope | Pass `user_config={"model": YourModel}` to `MemoryService` |
| Write with scope | Pass `user={"user_id": "..."}` to every `memorize()` and `create_memory_item()` call |
| Read with scope | Pass `where={"user_id": "..."}` to every `retrieve()` and list/search call |
| Validate | Trust memU to reject unknown `where` fields; do not add a manual post-filter |
