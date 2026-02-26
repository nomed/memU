# How to Add Persistent Conversation Memory to a Python Chatbot

> **Document type:** How-to — a task-focused guide for a specific goal.

**Goal:** Memorize conversation turns between sessions and inject retrieved memories into the next conversation's system prompt.

---

## Prerequisites

- Python 3.13+
- `memu` installed (`pip install memu` or `uv add memu`)
- An OpenAI API key exported as `OPENAI_API_KEY`

---

## Overview

The pattern has three steps per session:

1. **At session end:** call `memorize()` to extract and store memories from the conversation.
2. **At session start:** call `retrieve()` to fetch relevant memories for the current context.
3. **In the prompt:** inject the retrieved items into the system message before sending to the LLM.

---

## Step 1: Initialize MemoryService

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
)
```

This uses the default `inmemory` backend. For persistence across Python process restarts, see [howto-persistent-storage.md](howto-persistent-storage.md).

---

## Step 2: Format and memorize a conversation

memU expects conversation resources as a JSON file containing a list of `{"role": ..., "content": ...}` message objects. Use `tempfile` to create the file inline without needing external files:

```python
import json
import tempfile
import os

conversation = [
    {"role": "user",      "content": "Hi! I'm Alice. I'm a senior Python engineer."},
    {"role": "assistant", "content": "Nice to meet you, Alice! How can I help today?"},
    {"role": "user",      "content": "I prefer short, direct answers. No fluff please."},
    {"role": "assistant", "content": "Understood. I'll keep it concise."},
    {"role": "user",      "content": "I'm currently working on a FastAPI microservice."},
    {"role": "assistant", "content": "Got it. Happy to help with that."},
]

# Write the conversation to a temporary JSON file
with tempfile.NamedTemporaryFile(
    mode="w", suffix=".json", delete=False, encoding="utf-8"
) as f:
    json.dump(conversation, f)
    conversation_path = f.name
```

Now memorize it:

```python
import asyncio

async def memorize_conversation():
    result = await service.memorize(
        resource_url=conversation_path,
        modality="conversation",
        user={"user_id": "alice"},
    )
    print(f"Stored {len(result['items'])} memory items")
    print(f"Categories touched: {[c['name'] for c in result['categories']]}")
    return result

asyncio.run(memorize_conversation())
```

`memorize()` returns a dict with three keys:
- `resource`: the stored resource record
- `items`: extracted `MemoryItem` records (facts, preferences, events)
- `categories`: updated `MemoryCategory` summaries

Clean up the temp file after memorization:

```python
os.unlink(conversation_path)
```

---

## Step 3: Retrieve memories for the next turn

At the start of a new conversation — or before any LLM call — retrieve the most relevant memories for the current context:

```python
async def retrieve_memories(user_message: str) -> list[dict]:
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": user_message}}],
        where={"user_id": "alice"},
        method="rag",   # fast, embedding-based (default)
    )
    return result.get("items", [])
```

`retrieve()` returns:
- `categories`: relevant category summaries
- `items`: the most relevant individual memory items
- `resources`: originating source records (if recalled)
- `next_step_query`: a reformulated query suggestion for chained calls

---

## Step 4: Inject memories into the system prompt

Build a system prompt that includes the retrieved memories, then pass the full message list to your LLM:

```python
def build_system_prompt(memory_items: list[dict]) -> str:
    base = "You are a helpful assistant."
    if not memory_items:
        return base

    memories_text = "\n".join(
        f"- {item['summary']}" for item in memory_items if item.get("summary")
    )
    return (
        f"{base}\n\n"
        "## What you know about this user\n"
        f"{memories_text}\n\n"
        "Use this context to personalize your responses."
    )
```

---

## Complete self-contained example

The following script runs the full cycle — memorize a past conversation, then start a new turn with injected memory context — without any external files:

```python
"""
Persistent conversation memory example.

Usage:
    export OPENAI_API_KEY=sk-...
    python conversation_memory.py
"""

import asyncio
import json
import os
import tempfile

from memu.app import MemoryService


async def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    # 1. Initialize the service
    service = MemoryService(
        llm_profiles={
            "default": {
                "api_key": api_key,
                "chat_model": "gpt-4o-mini",
            },
        },
    )

    # 2. Simulate a past conversation
    past_conversation = [
        {"role": "user",      "content": "Hi! I'm Alice, a senior Python engineer."},
        {"role": "assistant", "content": "Great to meet you, Alice!"},
        {"role": "user",      "content": "I really dislike verbose, padded responses."},
        {"role": "assistant", "content": "Noted — I'll keep things concise for you."},
        {"role": "user",      "content": "My current project is a real-time data pipeline using Kafka."},
        {"role": "assistant", "content": "Interesting. Let me know if you need help with that."},
    ]

    # Write conversation to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(past_conversation, f)
        tmp_path = f.name

    try:
        # 3. Memorize the past conversation
        print("Memorizing past conversation...")
        mem_result = await service.memorize(
            resource_url=tmp_path,
            modality="conversation",
            user={"user_id": "alice"},
        )
        print(f"  → {len(mem_result['items'])} items extracted")
        print(f"  → Categories: {[c['name'] for c in mem_result['categories']]}")
    finally:
        os.unlink(tmp_path)

    # 4. New session: retrieve context for an incoming message
    new_user_message = "Can you help me think through my project architecture?"
    print(f"\nNew user message: '{new_user_message}'")
    print("Retrieving memories...")

    retrieval = await service.retrieve(
        queries=[{"role": "user", "content": {"text": new_user_message}}],
        where={"user_id": "alice"},
        method="rag",
    )

    items = retrieval.get("items", [])
    print(f"  → {len(items)} memory items retrieved")

    # 5. Build a memory-enriched system prompt
    def build_system_prompt(memory_items: list[dict]) -> str:
        base = "You are a helpful assistant."
        if not memory_items:
            return base
        memories_text = "\n".join(
            f"- {item['summary']}" for item in memory_items if item.get("summary")
        )
        return (
            f"{base}\n\n"
            "## What you know about this user\n"
            f"{memories_text}\n\n"
            "Use this context to personalize your responses."
        )

    system_prompt = build_system_prompt(items)
    print(f"\nSystem prompt (excerpt):\n{system_prompt[:400]}")

    # 6. (Illustration) The messages you would send to your LLM
    messages_for_llm = [
        {"role": "system",  "content": system_prompt},
        {"role": "user",    "content": new_user_message},
    ]
    print(f"\nReady to send {len(messages_for_llm)} messages to LLM.")
    print("The LLM now knows Alice's background without Alice repeating herself.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Notes

- **Scope isolation:** Always pass `where={"user_id": ...}` in multi-user apps. Without it, retrieval spans all records in the database.
- **Modality:** `modality="conversation"` tells the preprocessing pipeline that the resource is a chat transcript. Other supported values are `document`, `image`, `video`, and `audio`.
- **Memory growth:** Each call to `memorize()` with the same `user_id` adds new items and updates existing category summaries. The service deduplicates and merges at the category level.
- **Retrieval method:** `method="rag"` (the default) uses embedding similarity. Use `method="llm"` for deeper reasoning at higher latency and cost.
