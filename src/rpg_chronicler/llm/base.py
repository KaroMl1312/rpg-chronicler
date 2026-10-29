import time
from typing import Callable, Protocol, TypeVar

from ..config import LLM_MAX_RETRIES, LLM_RETRY_DELAY

T = TypeVar("T")


class LLMError(Exception):
    """Błąd wywołania modelu. `retryable` mówi, czy ponowna próba ma sens."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class LLMClient(Protocol):
    name: str

    def generate(self, prompt: str) -> str:
        """Wysyła prompt i zwraca odpowiedź modelu jako tekst."""
        ...


def with_retry(fn: Callable[[], T], description: str,
               attempts: int = LLM_MAX_RETRIES, delay: int = LLM_RETRY_DELAY) -> T:
    """Wywołuje `fn`, ponawiając próbę przy błędach LLMError oznaczonych jako retryable."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except LLMError as e:
            print(f"[BŁĄD Próba {attempt}/{attempts}] {description}: {e}")
            if not e.retryable or attempt == attempts:
                raise
            print(f"Czekam {delay} sekund na ponowną próbę...")
            time.sleep(delay)
    raise AssertionError("unreachable")
