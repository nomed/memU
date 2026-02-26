# GitHub Copilot / GitHub Models Provider

memU supports [GitHub Models](https://docs.github.com/en/github-models) as an OpenAI-compatible LLM provider.
GitHub Models exposes popular language and embedding models through a REST API that is fully
compatible with the OpenAI API format — so no code changes are required beyond pointing memU at
the correct endpoint and using a GitHub Personal Access Token (PAT) for authentication.

> **Note:** GitHub Models is the recommended way to use GitHub Copilot as the LLM backend for
> memU. It does not require a paid GitHub Copilot subscription for basic access; a free GitHub
> account with a PAT is sufficient. Copilot Individual/Business subscribers receive higher rate
> limits.

---

## How it works

GitHub Models is hosted at `https://models.inference.ai.azure.com` and accepts the same request
and response format as the OpenAI API. The `Authorization: Bearer <token>` header uses a GitHub
PAT instead of an OpenAI key. Because memU's `OpenAISDKClient` accepts an arbitrary `base_url`,
no new client code is needed.

memU includes a built-in `provider="github"` shortcut that sets the correct defaults
automatically.

---

## Prerequisites

1. A GitHub account (free or paid).
2. A **Personal Access Token (classic)** or a **fine-grained PAT** with the `models:read`
   permission scope.
   - Go to **GitHub → Settings → Developer settings → Personal access tokens**.
   - For fine-grained tokens, add `models:read` under "Permissions".
   - For classic tokens, no specific scope is required beyond basic account access.
3. `memu` installed (`pip install memu` or `uv add memu`).

---

## Configuration

### Environment variable

```bash
export GITHUB_TOKEN=github_pat_YOUR_TOKEN_HERE
```

### Using the `provider="github"` shortcut

The simplest way to configure memU for GitHub Models:

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
        },
    },
)
```

When `provider="github"` is set, memU automatically applies these defaults:

| Field | Default value |
|---|---|
| `base_url` | `https://models.inference.ai.azure.com` |
| `api_key` | `GITHUB_TOKEN` (env var name sentinel) |
| `chat_model` | `gpt-4o-mini` (available on GitHub Models) |
| `embed_model` | `text-embedding-3-small` (available on GitHub Models) |

### Overriding the model

GitHub Models provides access to many models. Override `chat_model` to use a different one:

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "gpt-4o",
            "embed_model": "text-embedding-3-large",
        },
    },
)
```

Models available on GitHub Models as of early 2026 include:

| Model | Type | Notes |
|---|---|---|
| `gpt-4o-mini` | Chat | Default; cost-efficient |
| `gpt-4o` | Chat | Higher quality, higher cost |
| `Phi-3.5-mini-instruct` | Chat | Open-weight alternative |
| `text-embedding-3-small` | Embedding | Default; recommended for most use cases |
| `text-embedding-3-large` | Embedding | Higher-dimensional, slower |

> **Note:** Model availability and rate limits change over time. Refer to
> [GitHub Models documentation](https://docs.github.com/en/github-models) for the current
> catalogue.

---

## Full example

```python
"""
memU with GitHub Models as LLM provider.

Usage:
    export GITHUB_TOKEN=github_pat_YOUR_TOKEN_HERE
    python example.py
"""

import asyncio
import os

from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "gpt-4o-mini",
            "embed_model": "text-embedding-3-small",
        },
    },
    database_config={
        "metadata_store": {"provider": "sqlite", "dsn": "sqlite:///./memory.db"},
    },
)


async def main() -> None:
    # Memorize a conversation
    import json, tempfile
    messages = [{"role": "user", "content": "I prefer concise answers."}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(messages, f)
        tmp = f.name

    result = await service.memorize(
        resource_url=tmp,
        modality="conversation",
        user={"user_id": "alice"},
    )
    print(f"Memorized {len(result['items'])} items")

    # Retrieve
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": "What do you know about my preferences?"}}],
        where={"user_id": "alice"},
        method="rag",
    )
    for item in result.get("items", []):
        print("-", item.get("summary", ""))


asyncio.run(main())
```

---

## Using the `httpx` client backend

If you configure `client_backend="httpx"`, the `provider` field selects the payload builder.
`"github"` maps to the OpenAI-compatible builder:

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "client_backend": "httpx",
            "api_key": os.environ["GITHUB_TOKEN"],
        },
    },
)
```

---

## Rate limits and quotas

GitHub Models enforces per-model rate limits that vary by account type:

| Account type | Limit |
|---|---|
| Free GitHub account | Low — suitable for evaluation and small projects |
| GitHub Copilot Individual | Moderate |
| GitHub Copilot Business / Enterprise | Higher |

For production workloads with sustained memory traffic, consider:
- Switching to the standard OpenAI API for higher and more predictable limits.
- Using a separate `"embedding"` profile with a different provider if GitHub Models
  embedding rate limits become a bottleneck.

---

## Troubleshooting

### `401 Unauthorized`

Your `GITHUB_TOKEN` is missing, expired, or does not have `models:read` permission.
Generate a new PAT and verify the scope.

### `429 Too Many Requests`

You have hit the GitHub Models rate limit for your account tier. Back off and retry, or
switch to a paid Copilot plan for higher limits.

### `404 Model Not Found`

The `chat_model` or `embed_model` you specified is not available on GitHub Models.
Check the [GitHub Models catalogue](https://github.com/marketplace/models) for current
availability.

### Embedding calls fail but chat works

Not all embedding models are available on all GitHub account tiers. Try
`text-embedding-3-small` (the default) before other models.
