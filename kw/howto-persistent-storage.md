# How to Choose and Configure a Persistent Storage Backend

> **Document type:** How-to — a task-focused guide for a specific goal.

**Goal:** Select the right storage backend for your memU deployment and configure it correctly.

---

## Prerequisites

- `memu` installed (`pip install memu` or `uv add memu`)
- For SQLite: no extra dependencies
- For Postgres: a running Postgres instance with `pgvector` extension available (see Step 3)

---

## Which backend should I use?

| | `inmemory` | `sqlite` | `postgres` |
|---|---|---|---|
| **Data survives restart** | No | Yes | Yes |
| **Setup required** | None | Path only | Server + extension |
| **Concurrent writers** | Single-process | Single-writer | Full concurrency |
| **Vector search** | Brute-force | Brute-force | pgvector (ANN) |
| **Typical scale** | < 1 k items | 1 k – 100 k items | 100 k + items |
| **Best for** | Tests, CI, prototypes | Single-user tools, small apps | Production multi-user SaaS |

> **Note:** Both `inmemory` and `sqlite` use brute-force cosine similarity for vector search. Query time scales linearly with item count. This is fine for small deployments; for larger ones use Postgres + pgvector.

---

## Step 1: Default — inmemory (no configuration needed)

If you do not provide a `database_config`, memU uses the in-memory backend:

```python
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={"default": {"api_key": "...", "chat_model": "gpt-4o-mini"}},
    # database_config omitted → inmemory by default
)
```

All data lives in Python dicts and lists. It is reset when the process exits. Use this for:
- Unit tests and integration tests
- Exploratory scripts where you do not need durability
- CI pipelines

---

## Step 2: SQLite — file-based persistence

SQLite stores data in a single file. No server is required. Specify the path via a `dsn` string:

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": "...", "chat_model": "gpt-4o-mini"}},
    database_config={
        "metadata_store": {
            "provider": "sqlite",
            "dsn": "sqlite:///./memory.db",   # relative path; use absolute for production
        },
    },
)
```

### DSN patterns

| Use case | DSN |
|---|---|
| Current directory | `sqlite:///./memory.db` |
| Absolute path | `sqlite:////home/user/data/memory.db` |
| In-memory SQLite (testing) | `sqlite:///:memory:` |

### What SQLite creates on first run

On first use, memU runs `ddl_mode="create"` by default, which issues `CREATE TABLE IF NOT EXISTS` statements for all four storage tables (resources, items, categories, relations). No manual schema setup is needed.

### Embedding storage in SQLite

Embeddings are stored as JSON text in the `sqlite` backend. Vector similarity is computed in Python using brute-force cosine scoring at query time. This is transparent to you — the same `retrieve()` API works identically to Postgres — but be aware that query latency grows with item count.

> **Tip:** For most personal tools and single-user applications, SQLite with a few thousand items is fast enough. If you notice retrieval latency above 1–2 seconds, consider migrating to Postgres.

---

## Step 3: Postgres — production-scale with pgvector

Postgres with the `pgvector` extension enables approximate nearest-neighbour (ANN) vector search and supports concurrent access from multiple processes or instances.

### Start Postgres with Docker

```bash
docker run -d \
  --name memu-postgres \
  -e POSTGRES_USER=memu \
  -e POSTGRES_PASSWORD=memu \
  -e POSTGRES_DB=memu \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

The `pgvector/pgvector` image includes the `vector` extension pre-built.

### Configure MemoryService to use Postgres

```python
service = MemoryService(
    llm_profiles={"default": {"api_key": "...", "chat_model": "gpt-4o-mini"}},
    database_config={
        "metadata_store": {
            "provider": "postgres",
            "dsn": "postgresql://memu:memu@localhost:5432/memu",
        },
    },
)
```

### What happens on first run

When `ddl_mode="create"` (the default), memU:

1. Runs `CREATE TABLE IF NOT EXISTS` for all storage tables
2. Attempts `CREATE EXTENSION IF NOT EXISTS vector` to enable pgvector
3. Derives the `vector_index` config automatically from `metadata_store.dsn` if not specified explicitly

You do not need to manually run migrations or create extensions.

### DSN patterns

| Use case | DSN |
|---|---|
| Local Docker | `postgresql://memu:memu@localhost:5432/memu` |
| With SSL | `postgresql://user:pass@host:5432/db?sslmode=require` |
| Environment variable | `os.environ["DATABASE_URL"]` |

---

## Step 4: Migrating from inmemory to SQLite between sessions

If you start with `inmemory` for development and want to switch to `sqlite` for production, the migration path is straightforward because all data is re-ingested through `memorize()`:

1. **Keep your source files** (conversation JSONs, documents) — these are the source of truth.
2. **Switch the backend** in your `MemoryService` config to `sqlite` with a file path.
3. **Re-run `memorize()`** for all source files. memU rebuilds the items and categories from scratch.

There is no export/import tool for in-memory data because raw sources are the canonical input. If you need to preserve injected memories (created via `create_memory_item()`), export them from the API before switching backends.

```python
# Before switching: list all items for a user
items = await service.list_memory_items(where={"user_id": "alice"})
# Store items externally, then re-inject after switching backend:
for item in items:
    await new_service.create_memory_item(
        memory_type=item["memory_type"],
        memory_content=item["summary"],
        memory_categories=item.get("categories", []),
        user={"user_id": "alice"},
    )
```

---

## Performance guidance summary

| Factor | inmemory | sqlite | postgres |
|---|---|---|---|
| Write throughput | Very high | Medium | High |
| Read (vector search) | O(n) in-process | O(n) in-process | Sub-linear with ANN index |
| Concurrent readers | Yes | Yes | Yes |
| Concurrent writers | No | No (WAL mode: limited) | Yes |
| Durability | None | File durability | ACID + replication available |
| Operational overhead | None | Near-zero | Server management |

> **Warning:** Do not use `sqlite` for applications with multiple concurrent writers (e.g. web servers handling parallel requests for the same database file). Use Postgres in those cases.
