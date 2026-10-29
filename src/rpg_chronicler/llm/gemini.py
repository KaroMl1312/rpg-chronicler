import time

from ..config import GEMINI_API_KEY, GEMINI_MIN_INTERVAL, GEMINI_MODEL
from .base import LLMError


class GeminiClient:
    """Darmowe API Gemini - z wymuszonym odstępem między zapytaniami."""

    name = "Gemini"

    def __init__(self, model: str = GEMINI_MODEL, min_interval: int = GEMINI_MIN_INTERVAL):
        if not GEMINI_API_KEY:
            raise LLMError("Brak GEMINI_API_KEY - ustaw go w pliku .env.", retryable=False)
        from google import genai
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = model
        self.min_interval = min_interval
        self._last_call = 0.0

    def generate(self, prompt: str) -> str:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if self._last_call and wait > 0:
            print(f"Czekam {wait:.0f}s przed kolejnym zapytaniem (ochrona przed limitami API)...")
            time.sleep(wait)
        try:
            response = self.client.models.generate_content(model=self.model, contents=prompt)
        except Exception as e:
            raise LLMError(str(e)) from e
        finally:
            self._last_call = time.monotonic()
        return response.text
