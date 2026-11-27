import os
import sys
from pathlib import Path

from . import envfile as _envfile
from . import settings as _settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IS_WINDOWS = sys.platform == "win32"  # także Python z MSYS2, na którym działa GUI na Windowsie


def venv_executable(name: str) -> Path:
    """Program z .venv projektu: .venv/bin/<nazwa> (Linux) albo .venv\\Scripts\\<nazwa>.exe (Windows)."""
    if IS_WINDOWS:
        return PROJECT_ROOT / ".venv" / "Scripts" / f"{name}.exe"
    return PROJECT_ROOT / ".venv" / "bin" / name


REPAIR_HINT = ("uruchom ponownie instaluj-windows.bat (w folderze programu)" if IS_WINDOWS
               else "w terminalu, w katalogu programu, uruchom ./sprawdz-srodowisko --napraw")


def use_bundled_ffmpeg(root: Path) -> None:
    """Windows: ffmpeg pobrany przez instaluj-windows.bat leży w <program>/ffmpeg/bin - dopisujemy go na początek
    PATH (wywołania ffmpeg/ffprobe i torchcodec, który szuka bibliotek DLL obok ffmpeg.exe)."""
    bundled = root / "ffmpeg" / "bin"
    path = os.environ.get("PATH", "")
    if (bundled / "ffmpeg.exe").exists() and str(bundled) not in path.split(os.pathsep):
        os.environ["PATH"] = str(bundled) + (os.pathsep + path if path else "")


use_bundled_ffmpeg(PROJECT_ROOT)
_envfile.load_into_environ()  # klucze API z .env (edycja: okno ustawień → Klucze API)

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
# Silnik rozpoznawania głosów: "pyannote" (PyTorch) albo "onnx" (te same sieci bez PyTorcha, ok. 6 razy szybciej)
DIARIZATION_ENGINES = ("pyannote", "onnx")
DIARIZATION_ENGINE = _setting("transkrypcja.rozpoznawanie_glosow", "pyannote")
if DIARIZATION_ENGINE not in DIARIZATION_ENGINES:
    print(f"[OSTRZEŻENIE] Nieznany silnik rozpoznawania głosów '{DIARIZATION_ENGINE}' - używam pyannote.")
    DIARIZATION_ENGINE = "pyannote"
# Próg grupowania głosów (pyannote 3.1); niższy = więcej osobnych mówców. Kampania może mieć własny (prog_glosow).
DIARIZATION_THRESHOLD = 0.7045654963945799
# Nagrywanie sesji w programie (recording.py): mikrofon (pusty = pierwszy z listy), filtr ffmpeg po nagraniu
RECORDING_FILTER_DEFAULT = "highpass=f=80, acompressor=threshold=-20dB:ratio=4:makeup=3dB:attack=0.2:release=1000"
RECORDING_DEVICE = _setting("nagrywanie.mikrofon", "")
RECORDING_FILTER = _setting("nagrywanie.filtr", RECORDING_FILTER_DEFAULT)
RECORDING_UPLOAD = _setting("nagrywanie.wyslij_na_drive", False)
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
