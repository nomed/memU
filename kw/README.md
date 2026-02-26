# memU Knowledge Base

Working documentation for the `memU` Python package. Organised using the [Diataxis](https://diataxis.fr/) framework.

---

## Explanation — understanding memU

| Document | Summary |
|---|---|
| [When to use memU](explanation-when-to-use-memu.md) | Core mental model, use-case guidance, backend and retrieval trade-offs, user scoping rationale |
| [memU as a proactive agent brain](explanation-memu-proactive-agent-brain.md) | Why memU is the memory layer of a proactive agent: the four roles, the two-loop architecture, category summaries as long-term memory |

## How-to guides — task-focused recipes

| Document | Task |
|---|---|
| [Conversation memory](howto-conversation-memory.md) | Add persistent memory to a Python chatbot |
| [Persistent storage](howto-persistent-storage.md) | Choose and configure inmemory / SQLite / Postgres backends |
| [User-scoped memory](howto-user-scoped-memory.md) | Isolate memory per user in a multi-user application |

## Tutorials — learning by doing

| Document | What you build |
|---|---|
| [AI research assistant](tutorial-ai-research-assistant.md) | A CLI research assistant with SQLite-backed persistent memory |
| [Proactive personal assistant](tutorial-proactive-personal-assistant.md) | A CLI proactive assistant with background memorization, proactive context injection, and CRUD memory management |

---

## Related project documentation

| Document | Location |
|---|---|
| Architecture reference | [`docs/architecture.md`](../docs/architecture.md) |
| Getting started quickstart | [`docs/tutorials/getting_started.md`](../docs/tutorials/getting_started.md) |
| SQLite configuration guide | [`docs/sqlite.md`](../docs/sqlite.md) |
| LangGraph integration | [`docs/langgraph_integration.md`](../docs/langgraph_integration.md) |
| Grok (xAI) provider | [`docs/integrations/grok.md`](../docs/integrations/grok.md) |
| GitHub Copilot / GitHub Models provider | [`docs/providers/github-copilot.md`](../docs/providers/github-copilot.md) |
| Architectural decisions | [`docs/adr/`](../docs/adr/) |
