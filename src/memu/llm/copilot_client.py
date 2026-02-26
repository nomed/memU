"""GitHub Copilot LLM client with automatic token exchange and refresh.

The GitHub Copilot API requires a two-step authentication:

1. A long-lived GitHub OAuth token (from device-code flow or a PAT with
   Copilot access) is passed to
   ``https://api.github.com/copilot_internal/v2/token``.

2. That endpoint returns a short-lived Copilot API token (typically ~30 min)
   and embeds the actual proxy base URL in the token string as a
   ``proxy-ep=...`` field.

:class:`CopilotTokenManager` handles the exchange and in-memory caching,
refreshing automatically when the token is within 5 minutes of expiry.

:class:`CopilotSDKClient` wraps :class:`~memu.llm.openai_sdk.OpenAISDKClient`
and calls :class:`CopilotTokenManager` before every outbound request so that
token renewal is fully transparent to the rest of the application.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Literal

import httpx
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from memu.llm.openai_sdk import OpenAISDKClient

logger = logging.getLogger(__name__)

COPILOT_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_BASE_URL = "https://api.individual.githubcopilot.com"

# Refresh the Copilot token this many seconds before its stated expiry to
# avoid races between the token check and the actual API call.
_EXPIRY_MARGIN_SECS = 300


class CopilotTokenManager:
    """Exchanges and caches a short-lived GitHub Copilot API token.

    Parameters
    ----------
    github_token:
        A GitHub OAuth token (device-code flow) or Personal Access Token
        that has GitHub Copilot access.  This token is **never** sent to the
        Copilot proxy; it is only used to obtain a short-lived Copilot token.
    fallback_base_url:
        Base URL to use when the Copilot token does not contain a
        ``proxy-ep`` field.  Defaults to
        ``https://api.individual.githubcopilot.com``.
    """

    def __init__(
        self,
        github_token: str,
        fallback_base_url: str | None = None,
    ) -> None:
        self._github_token = github_token
        self._fallback_base_url = (fallback_base_url or DEFAULT_COPILOT_BASE_URL).rstrip("/")
        self._copilot_token: str | None = None
        self._expires_at: float = 0.0  # Unix timestamp in seconds
        self._base_url: str = self._fallback_base_url

    # ------------------------------------------------------------------
    # Public helpers (also used by tests)
    # ------------------------------------------------------------------

    @staticmethod
    def derive_base_url(token: str, fallback: str = DEFAULT_COPILOT_BASE_URL) -> str:
        """Derive the Copilot proxy base URL from the token's ``proxy-ep`` field.

        The Copilot token is a semicolon-delimited list of ``key=value`` pairs.
        One of them is ``proxy-ep=https://proxy.<host>``.  Following the same
        convention as openclaw, the host is transformed from ``proxy.*`` to
        ``api.*``.

        Returns *fallback* when no ``proxy-ep`` field is present.
        """
        match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token, re.IGNORECASE)
        proxy_ep = match.group(1).strip() if match else None
        if not proxy_ep:
            return fallback
        host = re.sub(r"^https?://", "", proxy_ep)
        host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
        return f"https://{host}"

    @staticmethod
    def _parse_expires_at(raw: Any) -> float:
        """Return the expiry as a Unix timestamp in **seconds**.

        GitHub returns ``expires_at`` as a Unix timestamp that may be expressed
        in seconds (< 10 000 000 000) or milliseconds (>= 10 000 000 000),
        mirroring the behaviour documented in openclaw.
        """
        if isinstance(raw, (int, float)):
            val = float(raw)
        else:
            val = float(int(str(raw).strip()))
        # Values >= 10^10 are milliseconds → convert to seconds.
        if val >= 10_000_000_000:
            val /= 1000.0
        return val

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _needs_refresh(self) -> bool:
        return self._copilot_token is None or time.time() >= (self._expires_at - _EXPIRY_MARGIN_SECS)

    async def get_token(self) -> tuple[str, str]:
        """Return ``(copilot_token, base_url)``, refreshing when near expiry."""
        if not self._needs_refresh():
            return self._copilot_token, self._base_url  # type: ignore[return-value]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                COPILOT_EXCHANGE_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._github_token}",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        token: str = data["token"]
        self._expires_at = self._parse_expires_at(data["expires_at"])
        self._copilot_token = token
        self._base_url = self.derive_base_url(token, self._fallback_base_url)
        logger.debug(
            "Copilot token refreshed: base_url=%s expires_at=%s",
            self._base_url,
            self._expires_at,
        )
        return self._copilot_token, self._base_url


class CopilotSDKClient:
    """OpenAI SDK client for the GitHub Copilot proxy with transparent token refresh.

    On first use — and whenever the short-lived Copilot token is near expiry —
    this client exchanges the long-lived GitHub OAuth token for a fresh Copilot
    token via :class:`CopilotTokenManager`.  All chat, summarize, vision, embed,
    and transcribe calls are then delegated to a cached
    :class:`~memu.llm.openai_sdk.OpenAISDKClient` instance.  The inner client
    is only recreated when the token changes.

    Parameters
    ----------
    github_token:
        Long-lived GitHub OAuth token or PAT used **only** for the token
        exchange; never sent directly to the Copilot proxy.
    chat_model:
        Model name for chat/completion calls (e.g. ``"gpt-4o"``).
    embed_model:
        Model name for embedding calls (e.g. ``"text-embedding-3-small"``).
    fallback_base_url:
        Base URL to use when the Copilot token does not embed a
        ``proxy-ep`` endpoint.
    embed_batch_size:
        Maximum number of texts per embedding API call.
    """

    def __init__(
        self,
        *,
        github_token: str,
        chat_model: str,
        embed_model: str,
        fallback_base_url: str = DEFAULT_COPILOT_BASE_URL,
        embed_batch_size: int = 1,
    ) -> None:
        self._token_manager = CopilotTokenManager(github_token, fallback_base_url)
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.embed_batch_size = embed_batch_size
        self._sdk: OpenAISDKClient | None = None
        self._sdk_token: str | None = None

    async def _get_sdk(self) -> OpenAISDKClient:
        """Return a ready :class:`OpenAISDKClient`, rebuilding only on token change."""
        token, base_url = await self._token_manager.get_token()
        if self._sdk is None or self._sdk_token != token:
            self._sdk = OpenAISDKClient(
                base_url=base_url,
                api_key=token,
                chat_model=self.chat_model,
                embed_model=self.embed_model,
                embed_batch_size=self.embed_batch_size,
            )
            self._sdk_token = token
        return self._sdk

    async def chat(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> tuple[str, ChatCompletion]:
        sdk = await self._get_sdk()
        return await sdk.chat(
            prompt,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            temperature=temperature,
        )

    async def summarize(
        self,
        text: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> tuple[str, ChatCompletion]:
        sdk = await self._get_sdk()
        return await sdk.summarize(text, max_tokens=max_tokens, system_prompt=system_prompt)

    async def vision(
        self,
        prompt: str,
        image_path: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> tuple[str, ChatCompletion]:
        sdk = await self._get_sdk()
        return await sdk.vision(prompt, image_path, max_tokens=max_tokens, system_prompt=system_prompt)

    async def embed(
        self,
        inputs: list[str],
    ) -> tuple[list[list[float]], CreateEmbeddingResponse | None]:
        sdk = await self._get_sdk()
        return await sdk.embed(inputs)

    async def transcribe(
        self,
        audio_path: str,
        *,
        prompt: str | None = None,
        language: str | None = None,
        response_format: Literal["text", "json", "verbose_json"] = "text",
    ) -> tuple[str, Any]:
        sdk = await self._get_sdk()
        return await sdk.transcribe(
            audio_path,
            prompt=prompt,
            language=language,
            response_format=response_format,
        )
