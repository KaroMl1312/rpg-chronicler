import json
import subprocess
import tempfile

from ..config import CLAUDE_CODE_MODEL, CLAUDE_CODE_TIMEOUT
from .base import LLMError

SYSTEM_PROMPT = "Jesteś asystentem piszącym teksty. Odpowiadasz wyłącznie treścią, o którą prosi użytkownik."


class ClaudeCodeClient:
    """Wywołuje lokalne Claude Code (`claude -p`), korzystając z limitów planu Pro/Max."""

    name = "Claude Code"

    def __init__(self, model: str | None = CLAUDE_CODE_MODEL, timeout: int = CLAUDE_CODE_TIMEOUT):
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--system-prompt", SYSTEM_PROMPT,
            "--tools", "",              # tylko tekst, bez dostępu do plików i komend
            "--strict-mcp-config",      # bez serwerów MCP
            "--no-session-persistence",
        ]
        if self.model:
            cmd += ["--model", self.model]

        try:
            # Neutralny katalog roboczy, żeby nie wczytywać CLAUDE.md z projektu
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout, cwd=tempfile.gettempdir())
        except FileNotFoundError:
            raise LLMError("Nie znaleziono komendy 'claude' - zainstaluj Claude Code i zaloguj się.",
                           retryable=False)
        except subprocess.TimeoutExpired:
            raise LLMError(f"Przekroczono limit czasu ({self.timeout}s).")

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            details = proc.stderr.strip() or proc.stdout.strip()[:500]
            raise LLMError(f"Nieoczekiwana odpowiedź Claude Code (kod {proc.returncode}): {details}")

        if proc.returncode != 0 or data.get("is_error"):
            raise LLMError(data.get("result") or proc.stderr.strip() or "Nieznany błąd Claude Code.")
        return data["result"]
