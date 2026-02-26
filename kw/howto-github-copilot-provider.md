# How to Use GitHub Copilot (GitHub Models) Instead of OpenAI

**Diataxis type: How-to**

This guide answers a single question: _I currently configure memU with my OpenAI API key. How do I switch to GitHub Copilot?_

The answer is a one-line change to `llm_profiles`. No other code changes are required.

---

## Goal

Replace the OpenAI LLM provider with **GitHub Copilot (GitHub Models)** in memU. GitHub Models exposes a fully OpenAI API-compatible endpoint at `https://models.inference.ai.azure.com`. memU has a built-in `provider="github"` shortcut that targets this endpoint automatically.

---

## Prerequisites

- memU installed (`pip install memu` or `uv add memu`)
- A GitHub account (free tier works; higher Copilot tiers give more generous rate limits)
- A GitHub Personal Access Token with `models:read` scope (see Step 1)

---

## Step 1: Create a GitHub Personal Access Token

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Give the token a name (e.g. `memu-github-models`)
4. Under **Permissions → Account permissions**, set **Models** to `Read-only` (`models:read`)
5. Click **Generate token** and copy the value

> **Note:** Classic tokens also work. When using a classic token, no specific scope is required — the token itself grants access to GitHub Models.

Set the token in your shell environment:

```bash
export GITHUB_TOKEN=github_pat_...
```

For persistent use, add this line to your `.bashrc`, `.zshrc`, or equivalent profile file.

---

## Step 2: Update `llm_profiles` — before and after

The only change is swapping the key name and adding `"provider": "github"`. Everything else — the model names, the service configuration — stays the same.

**Before (OpenAI):**

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "chat_model": "gpt-4o-mini",
            "embed_model": "text-embedding-3-small",
        },
    },
)
```

**After (GitHub Copilot / GitHub Models):**

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            # chat_model defaults to "gpt-4o-mini"         — same as OpenAI default
            # embed_model defaults to "text-embedding-3-small" — same as OpenAI default
        },
    },
)
```

The `provider="github"` shortcut automatically sets:

- `base_url = "https://models.inference.ai.azure.com"`
- `chat_model = "gpt-4o-mini"` (default, if not overridden)
- `embed_model = "text-embedding-3-small"` (default, if not overridden)

Because the default model names are identical to the OpenAI defaults, no further changes are needed for a standard setup.

---

## Step 3: Choose a different model (optional)

If you want to use a non-default model, pass `chat_model` or `embed_model` explicitly:

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

**Available models on GitHub Models:**

| Type | Model name | Notes |
|---|---|---|
| Chat | `gpt-4o-mini` | Default; fast and cost-efficient |
| Chat | `gpt-4o` | Higher capability |
| Chat | `Phi-3.5-mini-instruct` | Microsoft open model; lightweight |
| Embedding | `text-embedding-3-small` | Default; recommended |
| Embedding | `text-embedding-3-large` | Higher-dimensional vectors |

> **Note:** Model availability may vary by Copilot tier or GitHub account type. Check [GitHub Models documentation](https://docs.github.com/en/github-models) for the current list.

---

## Step 4: Using a separate embedding profile

If you want to route chat and embeddings through different providers, use the `"embedding"` profile key. memU uses `"embedding"` for embedding calls when present, falling back to `"default"` otherwise.

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "gpt-4o",
        },
        "embedding": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            "embed_model": "text-embedding-3-small",
        },
    },
)
```

This pattern is also useful for mixing providers — for example, using GitHub Models for chat and a self-hosted embedding endpoint for vectors.

---

## Verify it works

Run this snippet to confirm the provider is wired up correctly:

```python
import asyncio
import json
import os
import tempfile

from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
        },
    },
)


async def smoke_test() -> None:
    # Write a short conversation to a temp file and memorize it
    messages = [{"role": "user", "content": "GitHub Models is fully OpenAI API-compatible."}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(messages, f)
        tmp_path = f.name

    result = await service.memorize(
        resource_url=tmp_path,
        modality="conversation",
        user={"user_id": "test-user"},
    )
    print(f"Memorized {len(result['items'])} item(s) via GitHub Models")

    # Retrieve it back
    result = await service.retrieve(
        queries=[{"role": "user", "content": {"text": "What is GitHub Models?"}}],
        where={"user_id": "test-user"},
        method="rag",
    )
    for item in result.get("items", []):
        print("-", item.get("summary", ""))


asyncio.run(smoke_test())
```

If items are printed, the GitHub Models provider is working end-to-end.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` | Token missing, expired, or lacks `models:read` | Regenerate the PAT and re-export `GITHUB_TOKEN` |
| `429 Too Many Requests` | Rate limit on free or low-tier account | Add request delays; upgrade to GitHub Copilot Individual, Business, or Enterprise for higher limits |
| `404 model not found` | Model name typo or not available on your tier | Check the table in Step 3; use `gpt-4o-mini` as a safe default |
| Embedding calls fail, chat works | Embedding model not available on your tier | Explicitly set `"embed_model": "text-embedding-3-small"` — it is the most broadly available embedding model |

---

## When to stay on OpenAI

GitHub Models is well-suited for development, prototyping, and small-to-medium deployments. Prefer the standard OpenAI provider if you need:

- **High-throughput production workloads** with guaranteed SLAs and enterprise-grade rate limits
- **Audio transcription** (Whisper) or other OpenAI-specific API surfaces not exposed via GitHub Models
- **Fine-tuned models** or OpenAI Assistants API features

For those cases, keep `api_key: os.environ["OPENAI_API_KEY"]` and omit the `provider` field (or set `provider="openai"`).
