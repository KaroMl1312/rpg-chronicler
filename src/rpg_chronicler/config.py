import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Wczytuje zmienne KLUCZ=WARTOŚĆ z pliku .env (nie nadpisuje już ustawionych)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")

# --- KONFIGURACJA ŚCIEŻEK ---
RCLONE_AUDIO_REMOTE = "gdrive:Audio_sesje_rpg"
RCLONE_TXT_REMOTE = "gdrive:Transkrypcje_rpg"        # Folder na Google Drive dla plików .txt
RCLONE_SUMMARY_REMOTE = "gdrive:Podsumowania_rpg"    # Folder na Google Drive dla podsumowań

AUDIO_DIR = os.path.expanduser("~/Documents/Audio_sesje_rpg")
TXT_DIR = os.path.expanduser("~/Documents/Transkrypcje")
SUMMARY_DIR = os.path.expanduser("~/Documents/Podsumowania")

CAMPAIGNS_FILE = PROJECT_ROOT / "kampanie.toml"

MODEL_SIZE = "medium"
WHISPER_CPU_THREADS = max(1, (os.cpu_count() or 2) // 2)  # liczba rdzeni fizycznych
WHISPER_VAD = False          # pomijanie ciszy (szybciej, mniej "zmyślonych" zdań w ciszy)
WHISPER_BATCH_SIZE = 0       # >0 = tryb wsadowy BatchedInferencePipeline (zawsze z VAD)
DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
SUPPORTED_EXTS = [".m4a", ".mp3", ".wav", ".flac", ".ogg"]

# --- AI KONFIGURACJA (sekrety z .env) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

# Dostawca LLM: "claude-code" (plan Pro/Max przez `claude -p`), "anthropic" (płatne API) lub "gemini"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude-code")
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 65  # sekundy między próbami

CLAUDE_CODE_MODEL = None     # None = domyślny model konta; można podać np. "sonnet" lub "opus"
CLAUDE_CODE_TIMEOUT = 900    # sekundy na jedno wywołanie

ANTHROPIC_MODEL = "claude-opus-5-5"
ANTHROPIC_EFFORT = "medium"  # low | medium | high | xhigh | max

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_MIN_INTERVAL = 60     # minimalny odstęp między zapytaniami (limity darmowego API)
