import os
from pathlib import Path

from . import settings as _settings

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

# Ustawienia użytkownika z ~/.config/rpg-chronicler/ustawienia.toml (GUI) nadpisują poniższe wartości domyślne
SETTINGS = _settings.load()


def _setting(key: str, default):
    return SETTINGS.get(key, default)


# --- KONFIGURACJA ŚCIEŻEK ---
RCLONE_AUDIO_REMOTE = _setting("google_drive.nagrania", "gdrive:Audio_sesje_rpg")
RCLONE_TXT_REMOTE = _setting("google_drive.transkrypcje", "gdrive:Transkrypcje_rpg")
RCLONE_SUMMARY_REMOTE = _setting("google_drive.podsumowania", "gdrive:Podsumowania_rpg")

AUDIO_DIR = os.path.expanduser(_setting("foldery.nagrania", "~/Documents/Audio_sesje_rpg"))
TXT_DIR = os.path.expanduser(_setting("foldery.transkrypcje", "~/Documents/Transkrypcje"))
SUMMARY_DIR = os.path.expanduser(_setting("foldery.podsumowania", "~/Documents/Podsumowania"))

# Kampanie leżą w folderze transkrypcji, więc synchronizują się z Google Drive (patrz campaigns.py)
CAMPAIGNS_FILENAME = "kampanie.toml"

MODEL_SIZE = _setting("transkrypcja.model", "medium")
WHISPER_CPU_THREADS = _setting("transkrypcja.watki", max(1, (os.cpu_count() or 2) // 2))  # rdzenie fizyczne
WHISPER_VAD = _setting("transkrypcja.pomijanie_ciszy", False)  # szybciej, mniej "zmyślonych" zdań w ciszy
WHISPER_NAME_HINTS = _setting("transkrypcja.podpowiedz_nazw", True)  # słownik kampanii jako hotwords Whispera
WHISPER_BATCH_SIZE = 0       # >0 = tryb wsadowy BatchedInferencePipeline (zawsze z VAD)
DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
SUPPORTED_EXTS = [".m4a", ".mp3", ".wav", ".flac", ".ogg"]

# --- AI KONFIGURACJA (sekrety z .env) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

# Obrazki haseł kampanii: Cloudflare Workers AI (darmowe 10 000 „neuronów” dziennie ≈ 200 obrazków FLUX schnell)
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")   # tylko uprawnienie Workers AI (Read + Edit)
IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
IMAGE_STEPS = 4   # FLUX schnell: 1–8 kroków; 4 = dobra jakość, ok. 43 neurony na obrazek

# Dostawca LLM: "claude-code" (plan Pro/Max przez `claude -p`), "anthropic" (płatne API) lub "gemini"
LLM_PROVIDER = _setting("ai.dostawca", os.environ.get("LLM_PROVIDER", "claude-code"))
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 65  # sekundy między próbami

CLAUDE_CODE_MODEL = _setting("ai.model_claude_code", "") or None  # None = domyślny model konta; np. "sonnet"
# Po każdej nowej kronice AI proponuje nowe nazwy do słownika kampanii (do zatwierdzenia w GUI)
GLOSSARY_PROPOSALS = _setting("ai.propozycje_slownika", True)
# Po każdej nowej kronice AI pisze jej skrót (kilka punktów z najważniejszymi wydarzeniami)
CHRONICLE_BRIEF = _setting("ai.skrot_kroniki", True)
# Po każdej nowej kronice AI wybiera cytaty z sesji (po jednym na postać + 2-3 najlepsze) (PDF, Discord)
CHRONICLE_QUOTES = _setting("ai.cytaty", True)
# Kronika w dwóch krokach: z każdej części transkrypcji (~45 min) lista wydarzeń, potem kronika z tych list
CHRONICLE_TWO_STEP = _setting("ai.kronika_etapami", True)
CHRONICLE_PART_SECONDS = 45 * 60
# Po każdej nowej kronice AI proponuje zaktualizowany stan kampanii (wątki, BN-i, zasoby; do zatwierdzenia)
CAMPAIGN_MEMORY = _setting("ai.pamiec_kampanii", True)

CLAUDE_CODE_TIMEOUT = 900    # sekundy na jedno wywołanie

ANTHROPIC_MODEL = "claude-opus-5-5"
ANTHROPIC_EFFORT = "medium"  # low | medium | high | xhigh | max

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_MIN_INTERVAL = 60     # minimalny odstęp między zapytaniami (limity darmowego API)
