import unittest
from unittest.mock import patch

from memu.app.settings import LLMConfig
from memu.llm.backends.github import GitHubModelsBackend
from memu.llm.openai_sdk import OpenAISDKClient


class TestGitHubModelsProvider(unittest.IsolatedAsyncioTestCase):
    def test_settings_defaults(self):
        """Test that setting provider='github' sets the correct defaults."""
        config = LLMConfig(provider="github")
        self.assertEqual(config.base_url, "https://models.inference.ai.azure.com")
        self.assertEqual(config.api_key, "GITHUB_TOKEN")
        # chat_model stays at gpt-4o-mini — available on GitHub Models
        self.assertEqual(config.chat_model, "gpt-4o-mini")
        # embed_model stays at text-embedding-3-small — available on GitHub Models
        self.assertEqual(config.embed_model, "text-embedding-3-small")

    def test_settings_explicit_overrides_respected(self):
        """Test that explicit overrides are not clobbered by the provider defaults."""
        config = LLMConfig(
            provider="github",
            chat_model="gpt-4o",
            embed_model="text-embedding-3-large",
        )
        self.assertEqual(config.chat_model, "gpt-4o")
        self.assertEqual(config.embed_model, "text-embedding-3-large")

    @patch("memu.llm.openai_sdk.AsyncOpenAI")
    async def test_client_initialization_with_github_config(self, mock_async_openai):
        """Test that OpenAISDKClient initializes with the GitHub Models base URL."""
        config = LLMConfig(provider="github")

        client = OpenAISDKClient(
            base_url=config.base_url,
            api_key="fake-github-pat",  # In real app: os.getenv(config.api_key)
            chat_model=config.chat_model,
            embed_model=config.embed_model,
        )

        mock_async_openai.assert_called_with(
            api_key="fake-github-pat",
            base_url="https://models.inference.ai.azure.com",
        )
        self.assertEqual(client.chat_model, "gpt-4o-mini")

    def test_github_backend_payload_parsing(self):
        """Test that GitHubModelsBackend parses responses correctly (inherited from OpenAI)."""
        backend = GitHubModelsBackend()

        dummy_response = {
            "choices": [{"message": {"content": "GitHub Models response", "role": "assistant"}}]
        }

        result = backend.parse_summary_response(dummy_response)
        self.assertEqual(result, "GitHub Models response")
