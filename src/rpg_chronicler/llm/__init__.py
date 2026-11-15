from ..config import LLM_PROVIDER
from .base import LLMClient, LLMError, generate, with_retry

__all__ = ["LLMClient", "LLMError", "LazyClient", "generate", "with_retry", "get_client"]


class LazyClient:
    """Tworzy klienta LLM dopiero przy pierwszym użyciu (np. nie wymaga klucza, gdy nie ma nic do zrobienia)."""

    def __init__(self, provider: str):
        self.provider = provider
        self._client: LLMClient | None = None

    def get(self) -> LLMClient:
        if self._client is None:
            self._client = get_client(self.provider)
        return self._client


def get_client(provider: str = LLM_PROVIDER) -> LLMClient:
    """Tworzy klienta LLM dla wybranego dostawcy (patrz LLM_PROVIDER w config.py)."""
    if provider == "claude-code":
        from .claude_code import ClaudeCodeClient
        return ClaudeCodeClient()
    if provider == "anthropic":
        from .anthropic_api import AnthropicClient
        return AnthropicClient()
    if provider == "gemini":
        from .gemini import GeminiClient
        return GeminiClient()
    raise LLMError(f"Nieznany dostawca LLM: '{provider}' (dostępne: claude-code, anthropic, gemini)",
                   retryable=False)
