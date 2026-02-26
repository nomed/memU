# How to Use GitHub Copilot Instead of OpenAI

> **Document type:** How-to — a task-focused guide for a specific goal.

This guide answers: _I currently configure memU with my OpenAI API key. How do I switch to GitHub Copilot?_

memU supports **two different GitHub-based providers**.  Choose the one that matches your access:

| | `provider="copilot"` | `provider="github"` |
|---|---|---|
| **Requires** | GitHub Copilot subscription | Free GitHub account |
| **Auth** | GitHub OAuth token → auto-exchanged for Copilot token | GitHub PAT (`models:read`) |
| **Models** | All models on your Copilot plan | GitHub Models marketplace |

Jump to the section that applies to you:

- [Option A — GitHub Copilot subscription (real Copilot proxy)](#option-a--github-copilot-subscription-real-copilot-proxy)
- [Option B — GitHub Models (no subscription required)](#option-b--github-models-no-subscription-required)

---

## Option A — GitHub Copilot subscription (real Copilot proxy)

Use `provider="copilot"` to connect memU to the same proxy used by VS Code, JetBrains, and other
Copilot-enabled tools.  memU automatically exchanges your GitHub OAuth token for a short-lived
Copilot API token and refreshes it transparently — you never manage the short-lived token yourself.

### Step 1: Get a GitHub token with Copilot access

You need one of:

- A **GitHub Personal Access Token (classic)** — no specific scope required; your account must
  have an active Copilot Individual, Business, or Enterprise subscription.
- A **GitHub OAuth token obtained via device-code flow** — the same mechanism used by the
  VS Code Copilot extension (scope: `read:user`).

```bash
export GITHUB_TOKEN=your_github_token_here
```

### Step 2: Switch `llm_profiles`

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

**After (GitHub Copilot proxy):**

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "copilot",
            "api_key": os.environ["GITHUB_TOKEN"],  # long-lived GitHub token
            # chat_model defaults to "gpt-4o" — widely available on Copilot plans
            # embed_model defaults to "text-embedding-3-small"
        },
    },
)
```

`provider="copilot"` sets these defaults automatically:

| Field | Value |
|---|---|
| `base_url` | `https://api.individual.githubcopilot.com` (fallback; real URL comes from token) |
| `chat_model` | `gpt-4o` |
| `embed_model` | `text-embedding-3-small` |

> **Note:** `client_backend="sdk"` (the default) is required for automatic token exchange.
> Do not set `client_backend="httpx"` unless you are pre-supplying a valid Copilot token.

### Step 3: Choose a model (optional)

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "copilot",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "claude-sonnet-4.5",  # requires Copilot Business/Enterprise
        },
    },
)
```

Available models (depends on your Copilot plan):

| Model | Notes |
|---|---|
| `gpt-4o` | Default; broadly available on all paid plans |
| `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | Latest GPT-4 family |
| `claude-sonnet-4.5`, `claude-sonnet-4.6` | Anthropic Claude — Business/Enterprise |
| `o1`, `o1-mini`, `o3-mini` | OpenAI reasoning models |

### Step 4: Handle embeddings (if needed)

Embedding support via the Copilot proxy is not guaranteed.  If embedding calls fail, use a
separate `"embedding"` profile pointing at OpenAI or another provider:

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "copilot",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "gpt-4o",
        },
        "embedding": {
            "provider": "openai",
            "api_key": os.environ["OPENAI_API_KEY"],
            "embed_model": "text-embedding-3-small",
        },
    },
)
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401` on token exchange | Token missing, expired, or no active Copilot subscription | Check your GitHub token and subscription status |
| `401` on API calls | Model not covered by your plan | Switch to `gpt-4o` (available on all paid plans) |
| `429` | Rate limit | Reduce frequency; upgrade plan |
| `404` model not found | Model ID typo or not on your plan | Use `gpt-4o` as a safe fallback |
| Token exchange fails in CI | `GITHUB_TOKEN` in Actions lacks Copilot access | Store a dedicated PAT as a repository secret |

---

## Option B — GitHub Models (no subscription required)

`provider="github"` connects to [GitHub Models](https://github.com/marketplace/models), which
exposes OpenAI and other models through an OpenAI-compatible API.  No Copilot subscription is
needed; a free GitHub account with a PAT is sufficient.

### Step 1: Create a GitHub Personal Access Token

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Under **Permissions → Account permissions**, set **Models** to `Read-only`
4. Click **Generate token** and copy the value

> **Note:** Classic tokens also work with no specific scope.

```bash
export GITHUB_TOKEN=github_pat_...
```

### Step 2: Switch `llm_profiles`

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "github",
            "api_key": os.environ["GITHUB_TOKEN"],
            # chat_model: gpt-4o-mini (same as OpenAI default — no change needed)
            # embed_model: text-embedding-3-small (same as OpenAI default)
        },
    },
)
```

`provider="github"` defaults:

| Field | Value |
|---|---|
| `base_url` | `https://models.inference.ai.azure.com` |
| `chat_model` | `gpt-4o-mini` |
| `embed_model` | `text-embedding-3-small` |

### Available models

| Model | Type | Notes |
|---|---|---|
| `gpt-4o-mini` | Chat | Default; cost-efficient |
| `gpt-4o` | Chat | Higher quality |
| `Phi-3.5-mini-instruct` | Chat | Open-weight alternative |
| `text-embedding-3-small` | Embedding | Default |
| `text-embedding-3-large` | Embedding | Higher-dimensional |

### Rate limits

| Account type | Notes |
|---|---|
| Free | Low limits — evaluation and small projects |
| Copilot Individual | Moderate |
| Copilot Business / Enterprise | Higher |

### Troubleshooting

| Symptom | Fix |
|---|---|
| `401` | Regenerate the PAT and verify `models:read` scope |
| `429` | Add delays or upgrade to a paid Copilot plan |
| `404` model not found | Use `gpt-4o-mini` (safe default) |
| Embedding calls fail | Use `text-embedding-3-small` |

---

## When to stay on OpenAI

Both GitHub providers are well-suited for development and moderate production loads.
Prefer the standard `provider="openai"` if you need:

- **High-throughput workloads** with enterprise SLAs and predictable rate limits
- **Audio transcription** (Whisper) — not exposed by either GitHub provider
- **Fine-tuned models** or OpenAI Assistants API features

