from __future__ import annotations

from memu.llm.backends.openai import OpenAILLMBackend


class CopilotBackend(OpenAILLMBackend):
    """Backend for the GitHub Copilot proxy — OpenAI-compatible API.

    Token exchange and automatic refresh are handled by
    :class:`~memu.llm.copilot_client.CopilotSDKClient` when
    ``client_backend="sdk"`` (the default and recommended setting).

    When ``client_backend="httpx"`` the caller is responsible for providing
    a pre-exchanged, valid Copilot API token via ``api_key``.
    """

    name = "copilot"
    # The Copilot proxy uses the same endpoint paths as OpenAI.
