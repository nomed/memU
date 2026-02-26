# Tutorial: Build a Proactive Personal Assistant with memU

> **Document type:** Tutorial — a learning-oriented, step-by-step guide.

In this tutorial you will build a **command-line personal assistant** that remembers what you tell it, recalls that context before every response without being asked, and accumulates knowledge in the background without slowing down the conversation.

By the end you will understand how to:
- Initialize memU with SQLite for durable, cross-session memory
- Fire background memorization tasks with `asyncio.create_task` so they never block the user
- Inject retrieved context into the system prompt before each LLM call
- Let the user explicitly store preferences and goals via CRUD commands
- Observe proactive behavior: the assistant surfaces past context without being prompted

**Time to complete:** 25–35 minutes  
**Difficulty:** Intermediate

---

## What you will build

A CLI chat loop with the following properties:

- The assistant answers with the help of `gpt-4o-mini` via the OpenAI API
- Every N=3 turns, the conversation is memorized in the **background** — the user never waits for it
- Before every response, `retrieve()` fetches relevant facts from memory and injects them into the system prompt
- `/remember <text>` stores a fact explicitly via `create_memory_item()`
- `/context` prints the current category summaries so you can see what the assistant knows
- Memory is stored in a local SQLite file and survives process restarts

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.13+ | |
| `memu` | `pip install memu` or `uv add memu` |
| `openai` | `pip install openai` |
| `OPENAI_API_KEY` | Set in your environment |

```bash
pip install memu openai
export OPENAI_API_KEY=sk-...
```

---

## Architecture overview

The assistant runs two concurrent loops:

```
MAIN LOOP  (per turn, foreground)
─────────────────────────────────────────────────────
  1. retrieve()  →  fetch relevant memories for user input
  2. Build system prompt with injected context
  3. Call OpenAI chat completions  →  get response
  4. Print response to user
  5. Append to memorize buffer
  6. Every N turns: schedule_memorize()  →  non-blocking

BACKGROUND LOOP  (asyncio task, runs concurrently)
─────────────────────────────────────────────────────
  memorize():
    →  extract MemoryItem records from the conversation
    →  update MemoryCategory summaries
    →  store embeddings for future retrieval
```

`service.memorize()` and `openai.chat.completions.create()` serve different roles: the OpenAI client handles chat completions only; all memory operations go through `MemoryService`.

---

## Step 1: Initialize the memory service

Create `assistant.py` and add the imports and service initialization:

```python
"""
Proactive personal assistant — tutorial script.

Usage:
    export OPENAI_API_KEY=sk-...
    python assistant.py
"""

import asyncio
import json
import os
import tempfile

from openai import AsyncOpenAI

from memu.app import MemoryService

USER_ID = "user_1"
MEMORIZE_EVERY_N = 3
DB_PATH = "./assistant_memory.db"


def create_service() -> MemoryService:
    """Return a MemoryService backed by a local SQLite database."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

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
                {"name": "preferences", "description": "User preferences and communication style"},
                {"name": "goals",       "description": "User goals and intentions"},
                {"name": "habits",      "description": "Behavioral patterns and routines"},
                {"name": "context",     "description": "Current working context and tasks"},
                {"name": "knowledge",   "description": "Facts, skills, and domain knowledge"},
            ],
        },
    )
```

**What this does:**

- `database_config` points memU at `assistant_memory.db`. The SQLite schema is created automatically on first run.
- `memorize_config` defines five categories. The `memorize()` pipeline maps extracted facts into these categories and maintains a running summary for each.
- The `USER_ID` constant scopes all memory to one logical user. In a multi-user application you would pass the authenticated user's identifier instead.

---

## Step 2: Background memorization

Add `schedule_memorize()` — a regular (non-`async`) function that submits a background task without blocking:

```python
def schedule_memorize(service: MemoryService, messages: list[dict]) -> None:
    """Submit memorization as a background asyncio task (fire-and-forget)."""

    async def _run() -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(messages, f)
            tmp_path = f.name
        try:
            result = await service.memorize(
                resource_url=tmp_path,
                modality="conversation",
                user={"user_id": USER_ID},
            )
            print(
                f"\n[Memory] Memorized {len(result['items'])} items "
                f"→ categories {[c['name'] for c in result['categories']]}"
            )
        except Exception as exc:
            print(f"\n[Memory] Memorization failed: {exc!r}")
        finally:
            os.unlink(tmp_path)

    asyncio.create_task(_run())
    print("[Memory] Background memorization scheduled.")
```

Key points:

- `asyncio.create_task(_run())` schedules the coroutine on the running event loop and returns immediately. The caller does not `await` it.
- The conversation is written to a temporary JSON file because `memorize()` expects a `resource_url`. The file is deleted in the `finally` block after ingestion.
- Errors are caught and logged without crashing the main loop.

> **Note:** `asyncio.create_task()` requires a running event loop. Call `schedule_memorize()` only from within an `async` function (such as the `chat()` loop below).

---

## Step 3: Proactive context retrieval

Add `load_context()` — called before every LLM response to inject relevant memories:

```python
async def load_context(service: MemoryService, user_message: str) -> str:
    """Retrieve relevant memories and format them as a context block for the system prompt."""
    try:
        result = await service.retrieve(
            queries=[{"role": "user", "content": {"text": user_message}}],
            where={"user_id": USER_ID},
            method="rag",
        )
    except Exception:
        return ""

    lines: list[str] = []

    # Category summaries: evolved digests of what the assistant knows about each topic
    for cat in result.get("categories", []):
        summary = cat.get("summary") or ""
        if summary:
            lines.append(f"[{cat['name']}] {summary}")

    # Individual memory items: specific facts relevant to this query
    for item in result.get("items", []):
        summary = item.get("summary", "")
        if summary:
            lines.append(f"- {summary}")

    return "\n".join(lines)
```

`retrieve()` uses embedding similarity (`method="rag"`) to find the most relevant categories and items for the current user message. The returned `categories` contain the LLM-maintained summaries — compact digests of everything stored in that topic. The returned `items` are the highest-scoring individual facts.

> **Tip:** On the first few turns before any memorization has run, `load_context()` returns an empty string. The system prompt falls back to a plain instruction, and the assistant behaves as a standard chatbot. After the first background memorization completes, subsequent turns will have rich context available.

---

## Step 4: The conversation loop

Add the main `chat()` function:

```python
async def chat(service: MemoryService, openai_client: AsyncOpenAI) -> None:
    """Main conversation loop with proactive context injection and background memorization."""
    conversation_history: list[dict] = []  # sent to OpenAI for multi-turn coherence
    memorize_buffer: list[dict] = []       # flushed to memU every N turns
    turn = 0

    print("Proactive Personal Assistant")
    print("Commands: /remember <text>  |  /context  |  quit")
    print("-" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        # --- Explicit memory commands (Step 5) ---
        if user_input.startswith("/remember "):
            fact = user_input[len("/remember "):].strip()
            if fact:
                await service.create_memory_item(
                    memory_type="profile",
                    memory_content=fact,
                    memory_categories=["preferences"],
                    user={"user_id": USER_ID},
                )
                print(f"[Memory] Stored: {fact!r}")
            continue

        if user_input == "/context":
            result = await service.list_memory_categories(where={"user_id": USER_ID})
            cats = result.get("categories", [])
            if cats:
                print("\n[Memory] What I know about you:")
                for cat in cats:
                    summary = cat.get("summary") or "(no summary yet)"
                    print(f"  {cat['name']}: {summary}")
            else:
                print("[Memory] No categories stored yet.")
            continue

        # --- Proactive context injection ---
        context_block = await load_context(service, user_input)

        system_prompt = "You are a helpful, proactive personal assistant."
        if context_block:
            system_prompt += (
                "\n\n## What you know about this user\n"
                + context_block
                + "\n\nUse this context to personalize your responses proactively. "
                "Surface relevant past information without waiting to be asked."
            )

        # Keep the last 3 exchanges (6 messages) for multi-turn context
        messages_for_llm = [{"role": "system", "content": system_prompt}]
        messages_for_llm.extend(conversation_history[-6:])
        messages_for_llm.append({"role": "user", "content": user_input})

        # --- OpenAI chat completion (LLM call only) ---
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages_for_llm,
        )
        assistant_reply = response.choices[0].message.content or ""

        print(f"\nAssistant: {assistant_reply}")

        # Accumulate messages in both history and memorize buffer
        conversation_history.append({"role": "user",      "content": user_input})
        conversation_history.append({"role": "assistant", "content": assistant_reply})
        memorize_buffer.append(    {"role": "user",      "content": user_input})
        memorize_buffer.append(    {"role": "assistant", "content": assistant_reply})
        turn += 1

        # --- Schedule background memorization every N turns ---
        if turn % MEMORIZE_EVERY_N == 0:
            schedule_memorize(service, memorize_buffer.copy())
            memorize_buffer.clear()

    # Memorize any remaining messages at session end
    if memorize_buffer:
        print("\n[Memory] Session ended — memorizing remaining messages...")
        schedule_memorize(service, memorize_buffer.copy())
        await asyncio.sleep(0.1)  # allow the task to be scheduled
```

The loop accumulates messages in `memorize_buffer`. Every `MEMORIZE_EVERY_N` turns the buffer is copied, passed to `schedule_memorize()`, and cleared. The copy is important — the background task holds a reference to the list it received, so clearing the original does not affect the in-flight task.

---

## Step 5: Explicit memory management (CRUD)

The `/remember` and `/context` commands are already wired into the `chat()` loop above. Here is what each one does at the memU API level:

**`/remember <text>`** — calls `create_memory_item()` directly, bypassing `memorize()`:

```python
await service.create_memory_item(
    memory_type="profile",        # profile | event | record | note
    memory_content=fact,          # the text to store
    memory_categories=["preferences"],
    user={"user_id": USER_ID},
)
```

This is useful for explicit statements the user makes ("I prefer dark mode", "my goal is to launch by Q3") that should be stored immediately rather than waiting for the next background memorization cycle.

**`/context`** — calls `list_memory_categories()` to print what the assistant currently knows:

```python
result = await service.list_memory_categories(where={"user_id": USER_ID})
for cat in result["categories"]:
    print(cat["name"], "→", cat.get("summary"))
```

Running `/context` after a few turns of conversation lets you observe the category summaries being updated in real time as background memorization completes.

---

## Step 6: Entry point

Add `main()` and the entry point:

```python
async def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    service = create_service()
    openai_client = AsyncOpenAI(api_key=api_key)

    await chat(service, openai_client)

    # Wait for any background memorization tasks still in flight
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        print(f"\n[Memory] Flushing {len(pending)} background task(s)...")
        await asyncio.gather(*pending, return_exceptions=True)

    print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python assistant.py
```

---

## Step 7: Run and observe proactive behavior

Start a session and try this sequence:

```
You: Hi, I'm Alice. I'm a senior Python engineer who hates verbose answers.
Assistant: Hi Alice! ...

You: My main project right now is migrating a monolith to microservices.
Assistant: ...

You: I also prefer async Python over threading.
Assistant: ...
[Memory] Background memorization scheduled.
[Memory] Memorized 4 items → categories ['preferences', 'knowledge', 'context']
```

After the first memorization cycle completes (logged in `[Memory]` lines), start a new topic:

```
You: Can you help me think through a design decision?
Assistant: Of course, Alice! Given your preference for async Python and the
           microservices migration you're working on, here's how I'd approach it...
```

The assistant mentioned Alice's preference and her project **without being told again** in this turn. That is proactive behavior — the retrieved context was injected into the system prompt by `load_context()`.

Try `/context` to see the live category summaries:

```
You: /context
[Memory] What I know about you:
  preferences: Alice is a senior Python engineer who prefers async Python over threading
               and dislikes verbose, padded responses.
  context: Alice is migrating a monolith to microservices.
  knowledge: (no summary yet)
```

And use `/remember` to store an explicit fact immediately:

```
You: /remember My deadline for the migration is end of Q3.
[Memory] Stored: 'My deadline for the migration is end of Q3.'

You: What should I prioritize this week?
Assistant: Given your Q3 deadline for the microservices migration...
```

The deadline was available immediately after `/remember` — it did not need to wait for a background memorization cycle.

---

## Complete script

The full `assistant.py`, assembled in one place for copy-paste:

```python
"""
Proactive personal assistant — tutorial script.

Usage:
    export OPENAI_API_KEY=sk-...
    python assistant.py
"""

import asyncio
import json
import os
import tempfile

from openai import AsyncOpenAI

from memu.app import MemoryService

USER_ID = "user_1"
MEMORIZE_EVERY_N = 3
DB_PATH = "./assistant_memory.db"


def create_service() -> MemoryService:
    """Return a MemoryService backed by a local SQLite database."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return MemoryService(
        llm_profiles={"default": {"api_key": api_key, "chat_model": "gpt-4o-mini"}},
        database_config={
            "metadata_store": {"provider": "sqlite", "dsn": f"sqlite:///{DB_PATH}"},
        },
        memorize_config={
            "memory_categories": [
                {"name": "preferences", "description": "User preferences and communication style"},
                {"name": "goals",       "description": "User goals and intentions"},
                {"name": "habits",      "description": "Behavioral patterns and routines"},
                {"name": "context",     "description": "Current working context and tasks"},
                {"name": "knowledge",   "description": "Facts, skills, and domain knowledge"},
            ],
        },
    )


def schedule_memorize(service: MemoryService, messages: list[dict]) -> None:
    """Submit memorization as a background asyncio task (fire-and-forget)."""
    async def _run() -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(messages, f)
            tmp_path = f.name
        try:
            result = await service.memorize(
                resource_url=tmp_path,
                modality="conversation",
                user={"user_id": USER_ID},
            )
            print(
                f"\n[Memory] Memorized {len(result['items'])} items "
                f"→ categories {[c['name'] for c in result['categories']]}"
            )
        except Exception as exc:
            print(f"\n[Memory] Memorization failed: {exc!r}")
        finally:
            os.unlink(tmp_path)

    asyncio.create_task(_run())
    print("[Memory] Background memorization scheduled.")


async def load_context(service: MemoryService, user_message: str) -> str:
    """Retrieve relevant memories and format them as a context block for the system prompt."""
    try:
        result = await service.retrieve(
            queries=[{"role": "user", "content": {"text": user_message}}],
            where={"user_id": USER_ID},
            method="rag",
        )
    except Exception:
        return ""

    lines: list[str] = []
    for cat in result.get("categories", []):
        summary = cat.get("summary") or ""
        if summary:
            lines.append(f"[{cat['name']}] {summary}")
    for item in result.get("items", []):
        summary = item.get("summary", "")
        if summary:
            lines.append(f"- {summary}")
    return "\n".join(lines)


async def chat(service: MemoryService, openai_client: AsyncOpenAI) -> None:
    """Main conversation loop: proactive context injection + background memorization."""
    conversation_history: list[dict] = []
    memorize_buffer: list[dict] = []
    turn = 0

    print("Proactive Personal Assistant")
    print("Commands: /remember <text>  |  /context  |  quit")
    print("-" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        if user_input.startswith("/remember "):
            fact = user_input[len("/remember "):].strip()
            if fact:
                await service.create_memory_item(
                    memory_type="profile",
                    memory_content=fact,
                    memory_categories=["preferences"],
                    user={"user_id": USER_ID},
                )
                print(f"[Memory] Stored: {fact!r}")
            continue

        if user_input == "/context":
            result = await service.list_memory_categories(where={"user_id": USER_ID})
            cats = result.get("categories", [])
            if cats:
                print("\n[Memory] What I know about you:")
                for cat in cats:
                    summary = cat.get("summary") or "(no summary yet)"
                    print(f"  {cat['name']}: {summary}")
            else:
                print("[Memory] No categories stored yet.")
            continue

        context_block = await load_context(service, user_input)

        system_prompt = "You are a helpful, proactive personal assistant."
        if context_block:
            system_prompt += (
                "\n\n## What you know about this user\n"
                + context_block
                + "\n\nUse this context to personalize your responses proactively. "
                "Surface relevant past information without waiting to be asked."
            )

        messages_for_llm = [{"role": "system", "content": system_prompt}]
        messages_for_llm.extend(conversation_history[-6:])
        messages_for_llm.append({"role": "user", "content": user_input})

        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages_for_llm,
        )
        assistant_reply = response.choices[0].message.content or ""

        print(f"\nAssistant: {assistant_reply}")

        conversation_history.append({"role": "user",      "content": user_input})
        conversation_history.append({"role": "assistant", "content": assistant_reply})
        memorize_buffer.append(    {"role": "user",      "content": user_input})
        memorize_buffer.append(    {"role": "assistant", "content": assistant_reply})
        turn += 1

        if turn % MEMORIZE_EVERY_N == 0:
            schedule_memorize(service, memorize_buffer.copy())
            memorize_buffer.clear()

    if memorize_buffer:
        print("\n[Memory] Session ended — memorizing remaining messages...")
        schedule_memorize(service, memorize_buffer.copy())
        await asyncio.sleep(0.1)


async def main() -> None:
    """Entry point: initialize service and client, run chat loop, drain background tasks."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    service = create_service()
    openai_client = AsyncOpenAI(api_key=api_key)

    await chat(service, openai_client)

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        print(f"\n[Memory] Flushing {len(pending)} background task(s)...")
        await asyncio.gather(*pending, return_exceptions=True)

    print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## What you have learned

| Concept | Where you used it |
|---|---|
| `MemoryService` init with SQLite and custom categories | `create_service()` |
| Background memorization with `asyncio.create_task` | `schedule_memorize()` |
| Proactive context injection via `retrieve()` | `load_context()` and system prompt building |
| Multi-turn conversation history (rolling window) | `conversation_history[-6:]` in `chat()` |
| Explicit memory storage via `create_memory_item()` | `/remember` command |
| Inspecting category summaries via `list_memory_categories()` | `/context` command |
| Memory growth across sessions (SQLite persistence) | `DB_PATH = "./assistant_memory.db"` |

---

## Next steps

- **Scale to multiple users** by replacing the `USER_ID` constant with an authenticated user identifier and always passing it in `where=` and `user=`. See [howto-user-scoped-memory.md](howto-user-scoped-memory.md).
- **Switch to `method="llm"` retrieval** for deeper reasoning when embedding similarity alone misses nuanced context.
- **Add more categories** to the `memorize_config` to track domain-specific signals (e.g., `decisions`, `risks`, `blockers`).
- **Tune `MEMORIZE_EVERY_N`** — lower values keep memory fresher at the cost of more LLM calls per session; higher values batch more efficiently.
- **Use Postgres** for multi-user or high-concurrency deployments: see [howto-persistent-storage.md](howto-persistent-storage.md).
- **Understand the architecture** behind `memorize()` and `retrieve()` pipelines: see the [Architecture reference](../docs/architecture.md).
- **Explore the proactive agent pattern** in depth: see [memU as a proactive agent brain](explanation-memu-proactive-agent-brain.md).
