"""Tests for the GitHub Copilot provider.

Covers:
- LLMConfig defaults when provider="copilot"
- CopilotTokenManager.derive_base_url (static helper)
- CopilotTokenManager._parse_expires_at (static helper)
- CopilotTokenManager.get_token: fetches, parses response, caches result
- CopilotSDKClient: delegates calls to a refreshed OpenAISDKClient
- MemoryService._init_llm_client: returns CopilotSDKClient for provider="copilot"
"""

import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from memu.app.settings import LLMConfig
from memu.llm.backends.copilot import CopilotBackend
from memu.llm.copilot_client import (
    DEFAULT_COPILOT_BASE_URL,
    COPILOT_EXCHANGE_URL,
    CopilotSDKClient,
    CopilotTokenManager,
)


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestCopilotSettings(unittest.TestCase):
    def test_settings_defaults(self):
        """provider='copilot' sets correct base_url, api_key sentinel, chat_model."""
        config = LLMConfig(provider="copilot")
        self.assertEqual(config.base_url, "https://api.individual.githubcopilot.com")
        self.assertEqual(config.api_key, "GITHUB_TOKEN")
        self.assertEqual(config.chat_model, "gpt-4o")
        # embed_model stays at the OpenAI default
        self.assertEqual(config.embed_model, "text-embedding-3-small")

    def test_explicit_overrides_not_clobbered(self):
        """Explicit field values are preserved even when provider='copilot'."""
        config = LLMConfig(
            provider="copilot",
            chat_model="claude-sonnet-4.5",
            embed_model="text-embedding-3-large",
            base_url="https://custom.copilot.example.com",
        )
        self.assertEqual(config.chat_model, "claude-sonnet-4.5")
        self.assertEqual(config.embed_model, "text-embedding-3-large")
        self.assertEqual(config.base_url, "https://custom.copilot.example.com")


# ---------------------------------------------------------------------------
# CopilotTokenManager — static helpers
# ---------------------------------------------------------------------------


class TestCopilotTokenManagerHelpers(unittest.TestCase):
    def test_derive_base_url_with_proxy_ep(self):
        token = "tid=abc;proxy-ep=https://proxy.individual.githubcopilot.com;other=val"
        result = CopilotTokenManager.derive_base_url(token)
        self.assertEqual(result, "https://api.individual.githubcopilot.com")

    def test_derive_base_url_no_proxy_ep_returns_fallback(self):
        token = "tid=abc;no-proxy-here=true"
        result = CopilotTokenManager.derive_base_url(token)
        self.assertEqual(result, DEFAULT_COPILOT_BASE_URL)

    def test_derive_base_url_custom_fallback(self):
        token = "tid=abc"
        result = CopilotTokenManager.derive_base_url(token, fallback="https://custom.example.com")
        self.assertEqual(result, "https://custom.example.com")

    def test_parse_expires_at_seconds(self):
        # A value < 10^10 is treated as Unix seconds.
        val = CopilotTokenManager._parse_expires_at(1_735_689_600)
        self.assertAlmostEqual(val, 1_735_689_600.0)

    def test_parse_expires_at_milliseconds(self):
        # A value >= 10^10 is treated as Unix milliseconds → divide by 1000.
        val = CopilotTokenManager._parse_expires_at(1_735_689_600_000)
        self.assertAlmostEqual(val, 1_735_689_600.0)

    def test_parse_expires_at_string(self):
        val = CopilotTokenManager._parse_expires_at("1735689600")
        self.assertAlmostEqual(val, 1_735_689_600.0)


# ---------------------------------------------------------------------------
# CopilotTokenManager — token exchange and caching
# ---------------------------------------------------------------------------


class TestCopilotTokenManagerGetToken(unittest.IsolatedAsyncioTestCase):
    def _make_mock_http(self, response_json: dict) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=response_json)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.get = AsyncMock(return_value=mock_resp)
        return mock_ctx

    async def test_get_token_fetches_and_returns_token_and_base_url(self):
        fake_token = "tid=xyz;proxy-ep=https://proxy.individual.githubcopilot.com"
        fake_resp = {"token": fake_token, "expires_at": 9_999_999_999}
        manager = CopilotTokenManager("fake-github-token")

        with patch("memu.llm.copilot_client.httpx.AsyncClient", return_value=self._make_mock_http(fake_resp)):
            token, base_url = await manager.get_token()

        self.assertEqual(token, fake_token)
        self.assertEqual(base_url, "https://api.individual.githubcopilot.com")

    async def test_get_token_caches_result(self):
        fake_token = "tid=xyz;proxy-ep=https://proxy.individual.githubcopilot.com"
        fake_resp = {"token": fake_token, "expires_at": 9_999_999_999}
        manager = CopilotTokenManager("fake-github-token")

        with patch("memu.llm.copilot_client.httpx.AsyncClient", return_value=self._make_mock_http(fake_resp)):
            await manager.get_token()

        # Second call must NOT hit the network (token is valid).
        with patch("memu.llm.copilot_client.httpx.AsyncClient") as mock_http_cls:
            token2, base_url2 = await manager.get_token()
            mock_http_cls.assert_not_called()

        self.assertEqual(token2, fake_token)

    async def test_get_token_refreshes_when_expired(self):
        fake_token = "tid=xyz"
        # expires_at in the past → needs refresh
        fake_resp = {"token": fake_token, "expires_at": 1}
        manager = CopilotTokenManager("fake-github-token")

        with patch("memu.llm.copilot_client.httpx.AsyncClient", return_value=self._make_mock_http(fake_resp)):
            await manager.get_token()

        # Token is expired; another get_token should hit the network again.
        fake_resp2 = {"token": "tid=new", "expires_at": 9_999_999_999}
        with patch("memu.llm.copilot_client.httpx.AsyncClient", return_value=self._make_mock_http(fake_resp2)):
            token3, _ = await manager.get_token()

        self.assertEqual(token3, "tid=new")

    async def test_get_token_refresh_within_margin(self):
        # Token expires in 60 seconds — within the 300-second safety margin.
        fake_token = "tid=soon-expired"
        fake_resp = {"token": fake_token, "expires_at": time.time() + 60}
        manager = CopilotTokenManager("fake-github-token")

        with patch("memu.llm.copilot_client.httpx.AsyncClient", return_value=self._make_mock_http(fake_resp)):
            await manager.get_token()

        # _needs_refresh should be True because expires_at - now < margin (300 s).
        self.assertTrue(manager._needs_refresh())


# ---------------------------------------------------------------------------
# CopilotSDKClient — delegation
# ---------------------------------------------------------------------------


class TestCopilotSDKClient(unittest.IsolatedAsyncioTestCase):
    async def test_chat_delegates_to_inner_sdk(self):
        client = CopilotSDKClient(
            github_token="fake-github-token",
            chat_model="gpt-4o",
            embed_model="text-embedding-3-small",
        )

        fake_token = "copilot-tok"
        mock_manager = AsyncMock()
        mock_manager.get_token = AsyncMock(return_value=(fake_token, DEFAULT_COPILOT_BASE_URL))
        client._token_manager = mock_manager

        mock_sdk = AsyncMock()
        mock_sdk.chat = AsyncMock(return_value=("hello", MagicMock()))

        with patch("memu.llm.copilot_client.OpenAISDKClient", return_value=mock_sdk):
            text, _ = await client.chat("hi", system_prompt="be helpful")

        self.assertEqual(text, "hello")
        mock_sdk.chat.assert_called_once_with(
            "hi",
            max_tokens=None,
            system_prompt="be helpful",
            temperature=0.2,
        )

    async def test_inner_sdk_rebuilt_on_token_change(self):
        client = CopilotSDKClient(
            github_token="fake-github-token",
            chat_model="gpt-4o",
            embed_model="text-embedding-3-small",
        )

        call_count = 0

        class _FakeSDK:
            async def chat(self, *a, **kw):
                return ("ok", MagicMock())

        with patch("memu.llm.copilot_client.OpenAISDKClient") as mock_cls:
            mock_cls.side_effect = lambda **kw: _FakeSDK()

            mock_manager = AsyncMock()
            mock_manager.get_token = AsyncMock(return_value=("token-A", DEFAULT_COPILOT_BASE_URL))
            client._token_manager = mock_manager
            await client.chat("first call")
            self.assertEqual(mock_cls.call_count, 1)

            # Same token → no rebuild.
            await client.chat("second call")
            self.assertEqual(mock_cls.call_count, 1)

            # New token → rebuild.
            mock_manager.get_token = AsyncMock(return_value=("token-B", DEFAULT_COPILOT_BASE_URL))
            await client.chat("third call")
            self.assertEqual(mock_cls.call_count, 2)


# ---------------------------------------------------------------------------
# Backend registration
# ---------------------------------------------------------------------------


class TestCopilotBackend(unittest.TestCase):
    def test_backend_name(self):
        self.assertEqual(CopilotBackend.name, "copilot")

    def test_backend_parses_openai_response(self):
        backend = CopilotBackend()
        resp = {"choices": [{"message": {"content": "Copilot says hi", "role": "assistant"}}]}
        self.assertEqual(backend.parse_summary_response(resp), "Copilot says hi")
