from __future__ import annotations

from memu.llm.backends.openai import OpenAILLMBackend


class GitHubModelsBackend(OpenAILLMBackend):
    """Backend for GitHub Models — fully OpenAI-compatible API."""

    name = "github"
    # GitHub Models uses the same payload structure and response format as OpenAI.
    # The endpoint paths (/chat/completions, /embeddings) are identical.
