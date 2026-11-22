"""Plik .env z kluczami API: odczyt, zapis z okna ustawień i opis, skąd wziąć każdy klucz. Tylko stdlib.

Plik leży w katalogu programu (ścieżkę zmienia RPG_CHRONICLER_ENV - testy). Zapis zmienia tylko podane klucze,
resztę linii i komentarze zostawia, a plik ma prawa 600. Zapis aktualizuje też os.environ bieżącego procesu,
bo GUI przekazuje swoje środowisko komendom CLI, a te przy starcie nie nadpisują już ustawionych zmiennych.
"""
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ENV_VAR = "RPG_CHRONICLER_ENV"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

HEADER = "# Klucze API programu rpg-chronicler. Nie udostępniaj tego pliku - nie trafia do repozytorium.\n"


@dataclass(frozen=True)
class Key:
    name: str
    title: str
    prefix: str = ""  # typowy początek klucza - inny wygląda na pomyłkę (tylko ostrzeżenie)
    secret: bool = True  # w oknie ustawień ukryty jak hasło


@dataclass(frozen=True)
class Service:
    """Usługa z kluczami: opis do okna ustawień i linki do stron, na których się je zakłada."""
    title: str
    description: str
    keys: list[Key]
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (tytuł, podpowiedź, adres)


SERVICES = [
    Service(
        "Hugging Face – rozpoznawanie mówców",
        "Wymagany do transkrypcji: model pyannote, który rozpoznaje, kto mówi, pobiera się z Hugging Face. "
        "Konto i token są darmowe.",
        [Key("HUGGINGFACE_TOKEN", "Token Hugging Face", "hf_")],
        [("Utwórz token", "Konto → Access Tokens → Create new token, typ „Read”",
          "https://huggingface.co/settings/tokens"),
         ("Zaakceptuj licencję modelu diaryzacji", "Na stronie modelu kliknij „Agree and access repository”",
          "https://huggingface.co/pyannote/speaker-diarization-3.1"),
         ("Zaakceptuj licencję modelu segmentacji", "Drugi model, którego używa diaryzacja",
          "https://huggingface.co/pyannote/segmentation-3.0")]),
    Service(
        "Claude API (Anthropic)",
        "Potrzebny tylko dla dostawcy „Claude API (płatne)”. Przy Claude Code (plan Pro/Max) wystarczy "
        "zalogowana komenda claude, bez klucza.",
        [Key("ANTHROPIC_API_KEY", "Klucz API Anthropic", "sk-ant-")],
        [("Utwórz klucz", "Console → API Keys → Create Key; płatność za użycie (Billing)",
          "https://console.anthropic.com/settings/keys")]),
    Service(
        "Gemini (Google)",
        "Potrzebny tylko dla dostawcy „Gemini”. Google AI Studio ma darmowy limit zapytań.",
        [Key("GEMINI_API_KEY", "Klucz API Gemini")],
        [("Utwórz klucz", "Google AI Studio → Get API key → Create API key",
          "https://aistudio.google.com/apikey")]),
    Service(
        "Cloudflare – obrazki od AI",
        "Opcjonalne: obrazki postaci i miejsc w zakładce Kampanie. Darmowe konto ma dzienny limit "
        "(ok. 200 obrazków).",
        [Key("CLOUDFLARE_ACCOUNT_ID", "Account ID", secret=False), Key("CLOUDFLARE_API_TOKEN", "Token API")],
        [("Znajdź Account ID", "Strona główna konta → menu przy nazwie konta → Copy account ID",
          "https://dash.cloudflare.com/"),
         ("Utwórz token", "Create Token → szablon „Workers AI” (tylko uprawnienie Workers AI: Read, Edit)",
          "https://dash.cloudflare.com/profile/api-tokens")]),
]


def path() -> Path:
    return Path(os.environ[ENV_VAR]) if os.environ.get(ENV_VAR) else PROJECT_ROOT / ".env"


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    return key.strip(), value.strip().strip('"').strip("'")


def read(env_path: Path | None = None) -> dict[str, str]:
    env_path = env_path or path()
    try:
        text = env_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return dict(item for line in text.splitlines() if (item := _parse_line(line)))


def load_into_environ(env_path: Path | None = None) -> None:
    """Wczytuje .env do os.environ, nie nadpisując zmiennych ustawionych wcześniej (np. w powłoce)."""
    for key, value in read(env_path).items():
        os.environ.setdefault(key, value)


def get(key: str) -> str:
    """Bieżąca wartość klucza (po zapisie z okna ustawień - już nowa)."""
    return os.environ.get(key, "")


def clean(value: str) -> str:
    """Wklejony klucz bez spacji, nowych linii i cudzysłowów wokół."""
    return value.strip().strip('"').strip("'").strip()


def update(values: dict[str, str], env_path: Path | None = None) -> Path:
    """Zapisuje klucze w .env (pusty = bez wartości), zachowując pozostałe linie; tworzy plik, gdy go nie ma."""
    env_path = env_path or path()
    values = {key: clean(value) for key, value in values.items()}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = [HEADER.rstrip("\n")]
    pending = dict(values)
    result = []
    for line in lines:
        item = _parse_line(line)
        if item and item[0] in values:
            if item[0] in pending:  # pierwsze wystąpienie zamieniamy, powtórzenia usuwamy
                result.append(f"{item[0]}={pending.pop(item[0])}")
            continue
        result.append(line)
    result.extend(f"{key}={value}" for key, value in pending.items())

    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=env_path.parent, prefix=".env.", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:  # mkstemp tworzy plik z prawami 600
            f.write("\n".join(result) + "\n")
        os.replace(tmp, env_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    return env_path
