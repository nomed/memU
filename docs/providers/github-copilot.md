# GitHub Copilot Provider

memU supports two distinct ways to use GitHub as an LLM backend.
Choose the one that matches your access:

| | `provider="copilot"` | `provider="github"` |
|---|---|---|
| **What it is** | Real GitHub Copilot proxy (requires Copilot subscription) | GitHub Models marketplace (free tier available) |
| **Auth** | GitHub OAuth token → short-lived Copilot token (auto-exchanged) | GitHub PAT with `models:read` scope |
| **Token refresh** | Automatic (transparent to the app) | Not needed — PAT is long-lived |
| **Models** | All models on your Copilot plan (`gpt-4o`, Claude, etc.) | Models listed on GitHub Models marketplace |
| **Base URL** | Derived from Copilot token (`proxy-ep` field) | `https://models.inference.ai.azure.com` |
| **Recommended `client_backend`** | `"sdk"` (default) | `"sdk"` or `"httpx"` |

---

## `provider="copilot"` — GitHub Copilot proxy

This provider calls the real GitHub Copilot API — the same endpoint used by VS Code,
JetBrains, and other Copilot-enabled editors.

### How it works

Authentication happens in two steps:

1. A long-lived **GitHub OAuth token** (from device-code flow or a PAT with Copilot access)
   is exchanged at `https://api.github.com/copilot_internal/v2/token`.
2. The endpoint returns a **short-lived Copilot token** (~30 min) that embeds the actual
   proxy base URL as a `proxy-ep=...` field.

memU's `CopilotSDKClient` handles the exchange and in-memory caching automatically.
The token is refreshed 5 minutes before expiry; your application code never sees the
short-lived token.

### Prerequisites

- A GitHub account with an active **GitHub Copilot Individual, Business, or Enterprise**
  subscription.
- A GitHub OAuth token or Personal Access Token.  The minimal scope for a classic PAT is
  no specific scope beyond account access.  Device-code flow OAuth tokens work directly.

### Configuration

```bash
export GITHUB_TOKEN=your_github_oauth_token_or_pat
```

```python
import os
from memu.app import MemoryService

service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "copilot",
            "api_key": os.environ["GITHUB_TOKEN"],
        },
    },
)
```

`provider="copilot"` sets these defaults automatically:

| Field | Default value |
|---|---|
| `base_url` | `https://api.individual.githubcopilot.com` (fallback; real URL comes from token) |
| `api_key` | `GITHUB_TOKEN` sentinel |
| `chat_model` | `gpt-4o` |
| `embed_model` | `text-embedding-3-small` |

### Available models

Model availability depends on your Copilot plan.  Common models include:

| Model | Notes |
|---|---|
| `gpt-4o` | Default; broadly available |
| `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | Latest GPT-4 family |
| `claude-sonnet-4.5`, `claude-sonnet-4.6` | Anthropic Claude (Enterprise/Business) |
| `o1`, `o1-mini`, `o3-mini` | OpenAI reasoning models |

Override `chat_model` to select a specific model:

```python
service = MemoryService(
    llm_profiles={
        "default": {
            "provider": "copilot",
            "api_key": os.environ["GITHUB_TOKEN"],
            "chat_model": "claude-sonnet-4.5",
        },
    },
)
```

> **Note:** Embedding support via the Copilot proxy is not guaranteed.  If embedding
> calls fail, point the `"embedding"` profile at a different provider
> (e.g. `provider="openai"` with `embed_model="text-embedding-3-small"`).

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401` on token exchange | Token missing, expired, or no Copilot subscription | Verify your GitHub token and subscription status |
| `401` on API call | Copilot token exchange succeeded but the Copilot plan does not cover the requested model | Switch to a model included in your plan |
| `429` | Rate limit on your Copilot plan | Reduce request frequency |
| `404` model not found | Model not available on your plan | Check available models on your Copilot dashboard |
| Token exchange fails in CI | `GITHUB_TOKEN` in Actions does not have Copilot access | Use a dedicated PAT stored as a repository secret |

---

## `provider="github"` — GitHub Models

GitHub Models (`https://models.inference.ai.azure.com`) exposes OpenAI and other models
through an OpenAI-compatible API.  It does not require a Copilot subscription; a free
GitHub account with a PAT and `models:read` scope is sufficient.

### Prerequisites

1. A GitHub account (free tier works).
2. A **Personal Access Token** (classic or fine-grained with `models:read` permission).
3. `memu` installed (`pip install memu` or `uv add memu`).

```bash
export GITHUB_TOKEN=github_pat_YOUR_TOKEN_HERE
```

### Configuration

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

`provider="github"` sets these defaults:

| Field | Default value |
|---|---|
| `base_url` | `https://models.inference.ai.azure.com` |
| `api_key` | `GITHUB_TOKEN` sentinel |
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

> **Note:** Model availability and rate limits change over time.  See the
> [GitHub Models catalogue](https://github.com/marketplace/models).

### Rate limits

| Account type | Limit |
|---|---|
| Free GitHub account | Low — evaluation and small projects |
| GitHub Copilot Individual | Moderate |
| GitHub Copilot Business / Enterprise | Higher |

### Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` | Regenerate PAT and verify `models:read` scope |
| `429 Too Many Requests` | Upgrade Copilot plan or add request delays |
| `404` model not found | Check available models in the catalogue |
| Embedding calls fail | Use `text-embedding-3-small` — most broadly available |

