# memU as a Proactive Agent Brain — Explanation

> **Document type:** Explanation — concepts, architecture, and rationale.

---

## The question: is memU the memory of an agent's brain?

Yes — and the analogy is precise, not decorative.

A large-language model is stateless by design. Every new call starts with a blank context window: no knowledge of yesterday's conversation, last week's preference, or the goal set three sessions ago. The only "memory" is what you pack into the prompt, which is finite, expensive, and discarded when the session ends.

This maps directly onto the distinction between **short-term and long-term memory** in cognitive science:

| Memory type | Human cognition | AI agent |
|---|---|---|
| **Short-term (working memory)** | Active, limited capacity (~7 items), lost quickly | The context window: fast but finite and ephemeral |
| **Long-term memory** | Durable, vast, reconstructed on retrieval | memU: persistent database, growing with each interaction |

memU is the long-term memory layer. It stores what the agent has learned, structures it into queryable categories, and reconstructs the relevant slice of that knowledge when needed — so the agent never has to ask "who are you, again?"

---

## What "proactive" means in agent terms

A **reactive agent** waits for instructions and acts only on what it is explicitly told in the current turn.

A **proactive agent** acts on what it *knows* — surfacing relevant context before being asked, continuing tasks across sessions, and anticipating needs from patterns it has observed.

Proactive behavior requires answers to questions the user never asked:

- "What did this user tell me about their work last week?"
- "What were they trying to accomplish the last time we spoke?"
- "What preferences have shaped their past choices?"
- "What tasks are still open?"

None of these questions can be answered from the current context window alone. They require durable, structured, queryable memory — which is exactly what memU provides.

Concretely, a proactive agent can:

- **Pre-fetch context** before a conversation starts, based on the topic or the user's identity
- **Anticipate needs** from a user's stored goals and habits
- **Surface relevant information** at the right moment without being prompted
- **Track tasks across sessions** and resume them autonomously

---

## The four roles memU plays in a proactive agent

| Role | What memU does | API used |
|---|---|---|
| **Passive learner** | Memorizes every interaction in the background without blocking the main conversation loop | `memorize()` as an `asyncio` background task |
| **Context injector** | Retrieves the most relevant facts before each agent response and injects them into the system prompt | `retrieve()` at the start of each turn |
| **Knowledge accumulator** | Builds and continuously updates category summaries (goals, habits, preferences) as new interactions arrive | Automatic — part of the `memorize()` pipeline |
| **Active memory manager** | Lets the agent (or the user) explicitly store, update, or delete specific knowledge | `create_memory_item()`, `update_memory_item()`, `delete_memory_item()` |

These four roles are not sequential phases — they run concurrently. The passive learner and knowledge accumulator operate in the background while the context injector and active memory manager operate in the foreground.

---

## The proactive memory loop

A proactive agent built on memU runs two concurrent loops:

```
MAIN LOOP  (per turn, foreground)
─────────────────────────────────────────────────────
  1. retrieve()  →  fetch relevant memories for this input
  2. Build system prompt  →  inject retrieved context
  3. LLM call  →  generate response with enriched context
  4. Return response to user
  5. Queue memorize() as background asyncio task (non-blocking)

BACKGROUND LOOP  (async, non-blocking)
─────────────────────────────────────────────────────
  memorize() running concurrently:
    →  parse and chunk the conversation resource
    →  extract MemoryItem records (facts, preferences, goals)
    →  assign items to MemoryCategory buckets
    →  update each category's summary with new information
    →  store embeddings for future vector retrieval
```

The critical design point is that `memorize()` runs as an `asyncio.create_task()` — it is submitted without `await`, so it never blocks the user waiting for a response. The background loop accumulates knowledge even between explicit user turns, and its results become available to the next `retrieve()` call.

In code, the separation looks like this:

```python
# Step 5 of the main loop — non-blocking memorization
def schedule_memorize(service: MemoryService, messages: list[dict]) -> None:
    async def _run():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(messages, f)
            tmp_path = f.name
        try:
            await service.memorize(
                resource_url=tmp_path,
                modality="conversation",
                user={"user_id": USER_ID},
            )
        finally:
            os.unlink(tmp_path)

    asyncio.create_task(_run())  # fire-and-forget
```

`asyncio.create_task()` schedules `_run()` on the running event loop and returns immediately. The main loop continues, the user gets a fast response, and memorization happens in the background.

---

## Why category summaries are the "long-term memory"

memU's memory hierarchy has three levels:

```
Resource  →  individual conversation or document (raw input)
MemoryItem  →  a single extracted fact, preference, or goal
MemoryCategory  →  a topic digest: summary + all related items
```

The key layer for proactive behavior is `MemoryCategory.summary`.

Every time new `MemoryItem` records are assigned to a category (inside the `memorize()` pipeline), an LLM call updates the category's `summary` field to incorporate the new information. The summary is a **continuously evolving digest** — not a list of raw items, but a synthesized, human-readable account of everything the agent knows about that topic.

This mirrors how the human brain consolidates episodic memories (individual experiences) into semantic memory (general knowledge) during rest. The agent does not need to re-read hundreds of raw conversation turns; it reads the category summary and gets the distilled essence.

When `retrieve()` returns a category, the `summary` field is already the consolidated picture:

```python
result = await service.retrieve(
    queries=[{"role": "user", "content": {"text": "What are Alice's preferences?"}}],
    where={"user_id": "alice"},
    method="rag",
)

for cat in result["categories"]:
    print(cat["name"], "→", cat["summary"])
# preferences → Alice prefers concise, direct answers without filler text.
#               She is an experienced Python engineer and wants technical depth.
```

This summary was written and rewritten by the LLM across multiple `memorize()` calls, incorporating each new signal. The agent injects this directly into its system prompt — giving it an up-to-date, compact picture without scanning thousands of raw items.

---

## Proactive retrieval: `next_step_query`

`retrieve()` does not just return what it found — it also returns `next_step_query`, a reformulated query suggesting what the agent should look for next:

```python
result = await service.retrieve(
    queries=[{"role": "user", "content": {"text": "Can you help with my project?"}}],
    where={"user_id": "alice"},
    method="rag",
)

print(result["next_step_query"])
# → "What are Alice's current project goals and active tasks?"
```

This enables **chained proactive retrieval**: the agent can follow the suggestion to issue a second `retrieve()` call without waiting for the user to provide more context. The result is an agent that progressively gathers what it needs from its own memory, rather than asking the user to repeat themselves.

> **Note:** `next_step_query` is generated by the pipeline and reflects what the retrieval stage determined was still unresolved. Its quality improves as more memory accumulates.

---

## What makes memU different from a plain vector store

A vector store is a flat index: you embed text, store it, and retrieve the nearest neighbors. memU builds on that primitive but adds four structural layers that are essential for proactive agent behavior:

| Capability | Plain vector store | memU |
|---|---|---|
| **Storage model** | Flat embeddings | Structured hierarchy: Resource → MemoryItem → MemoryCategory |
| **Categorization** | Manual tagging | Automatic — the LLM assigns facts to named categories during `memorize()` |
| **Knowledge digests** | None — retrieve raw chunks | Category summaries: continuously updated, LLM-maintained digests |
| **Explicit correction** | Requires re-ingestion | CRUD layer: agent can update, delete, or override specific items directly |
| **User isolation** | Requires manual filtering | First-class scope fields (`user_id`, etc.) validated on every read and write |
| **Proactive signal** | None | `next_step_query` guides chained retrieval without user prompting |

The structural hierarchy means the agent has access to both fine-grained facts (individual `MemoryItem` records) and high-level knowledge (category summaries) — and can choose the right granularity for the task.

The CRUD layer means the agent is not just a passive consumer of its memory: it can correct mistakes, record explicit commitments, and prune outdated information. This is the difference between a log file and an actively maintained knowledge base.

---

## Summary

memU provides everything a proactive agent needs from a long-term memory layer:

1. **Durability** — memory survives process restarts and session boundaries
2. **Structure** — facts are organized into named, summarized categories, not a flat pile of embeddings
3. **Non-blocking accumulation** — `memorize()` runs in the background so the main loop stays fast
4. **Proactive injection** — `retrieve()` fetches the right slice of memory before every LLM call
5. **Active management** — the agent can explicitly write, update, and delete its own memory
6. **Multi-user isolation** — user scoping is structural, not an afterthought

Without a layer like this, an agent is permanently reactive and permanently amnesiac. With it, the agent grows more capable with every interaction — which is the foundation of any genuinely proactive system.

---

## Related documentation

- [When to use memU](explanation-when-to-use-memu.md) — use-case guidance, backend and retrieval trade-offs
- [Tutorial: Proactive personal assistant](tutorial-proactive-personal-assistant.md) — step-by-step implementation of the two-loop architecture
- [How to add conversation memory](howto-conversation-memory.md) — memorize conversations and inject retrieved context
- [Architecture reference](../docs/architecture.md) — runtime architecture and flow details
