from ..config import ANTHROPIC_EFFORT, ANTHROPIC_MODEL
from .base import LLMError


class AnthropicClient:
    """Płatne API Anthropic (klucz ANTHROPIC_API_KEY w .env)."""

    name = "Claude API"

    def __init__(self, model: str = ANTHROPIC_MODEL, effort: str = ANTHROPIC_EFFORT):
        try:
            import anthropic
        except ImportError:
            raise LLMError("Brak pakietu 'anthropic' - zainstaluj: pip install --user anthropic",
                           retryable=False)
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def generate(self, prompt: str) -> str:
        anthropic = self._anthropic
        try:
            # Streaming, bo transkrypcje są długie i odpowiedź też może być długa
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
            raise LLMError(str(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMError(str(e), retryable=e.status_code >= 500) from e

        if message.stop_reason == "refusal":
            raise LLMError("Model odmówił odpowiedzi.", retryable=False)
        if message.stop_reason == "max_tokens":
            print("[OSTRZEŻENIE] Odpowiedź została ucięta (limit max_tokens).")
        return "".join(block.text for block in message.content if block.type == "text")
