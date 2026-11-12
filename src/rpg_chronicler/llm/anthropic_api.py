from ..config import ANTHROPIC_EFFORT, ANTHROPIC_MODEL
from .base import LLMError


class AnthropicClient:
    """Płatne API Anthropic (klucz ANTHROPIC_API_KEY w .env)."""

    name = "Claude API"
    caches_prefix = True  # llm.generate(..., prefix=...) wysyła stały początek osobno, z cache

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

    def generate(self, prompt: str, prefix: str = "") -> str:
        """`prefix` - stały początek wspólny dla kilku zapytań z rzędu (części jednej sesji, zapytania po
        kronice); idzie jako osobny blok z cache (5 min, odświeżany każdym odczytem), reszta bez cache."""
        anthropic = self._anthropic
        content: str | list[dict] = prompt
        if prefix:
            content = [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": prompt}]
        try:
            # Streaming, bo transkrypcje są długie i odpowiedź też może być długa
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": content}],
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
        if prefix:
            usage = message.usage
            read = getattr(usage, "cache_read_input_tokens", 0) or 0
            written = getattr(usage, "cache_creation_input_tokens", 0) or 0
            print(f"[INFO] Cache API: odczyt {read} tokenów, zapis {written}, bez cache {usage.input_tokens}.")
        return "".join(block.text for block in message.content if block.type == "text")
