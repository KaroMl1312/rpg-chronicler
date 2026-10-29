"""Ustawienia kampanii z pliku kampanie.toml (system RPG, kontekst świata)."""
import tomllib
from dataclasses import dataclass
from functools import lru_cache

from .config import CAMPAIGNS_FILE


@dataclass(frozen=True)
class Campaign:
    key: str
    system: str
    context: str = ""


def campaign_key(session_name: str) -> str | None:
    """'Warhammer_261015' -> 'Warhammer'; bez '_' w nazwie -> None."""
    return session_name.split("_")[0] if "_" in session_name else None


@lru_cache
def load_campaigns(path: str = str(CAMPAIGNS_FILE)) -> dict[str, Campaign]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        print(f"[OSTRZEŻENIE] Błąd w pliku {path}: {e}")
        return {}
    return {
        key: Campaign(key, values.get("system", key), values.get("kontekst", "").strip())
        for key, values in data.items()
    }


def campaign_for(session_name: str) -> Campaign:
    """Kampania dla sesji: z kampanie.toml, a jeśli jej tam nie ma - z prefiksu nazwy pliku."""
    key = campaign_key(session_name)
    if key is None:
        return Campaign("", "RPG")
    return load_campaigns().get(key) or Campaign(key, key.replace("-", " ").title())
