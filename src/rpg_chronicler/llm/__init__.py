from ..config import LLM_PROVIDER
from .base import LLMClient, LLMError, with_retry

__all__ = ["LLMClient", "LLMError", "with_retry", "get_client"]


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
