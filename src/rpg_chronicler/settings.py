"""Ustawienia użytkownika w ~/.config/rpg-chronicler/ustawienia.toml (edytowane z GUI).

Plik zawiera tylko to, co użytkownik zmienił; brakujące klucze biorą wartości domyślne z config.py.
Ścieżkę można zmienić zmienną RPG_CHRONICLER_SETTINGS (używają jej testy).
Moduł nie importuje config.py (to config.py wczytuje ustawienia), tylko biblioteka standardowa.
"""
import json
import os
import tomllib
from pathlib import Path

ENV_VAR = "RPG_CHRONICLER_SETTINGS"

# klucz "sekcja.nazwa" -> typ wartości
FIELDS: dict[str, type] = {
    "ai.dostawca": str,
    "ai.model_claude_code": str,
    "ai.propozycje_slownika": bool,
    "ai.skrot_kroniki": bool,
    "ai.kronika_etapami": bool,
    "ai.pamiec_kampanii": bool,
    "transkrypcja.model": str,
    "transkrypcja.watki": int,
    "transkrypcja.pomijanie_ciszy": bool,
    "transkrypcja.podpowiedz_nazw": bool,
    "foldery.nagrania": str,
    "foldery.transkrypcje": str,
    "foldery.podsumowania": str,
    "google_drive.nagrania": str,
    "google_drive.transkrypcje": str,
    "google_drive.podsumowania": str,
}

# Sekcje z dowolnymi kluczami: [discord] Warhammer = "https://discord.com/api/webhooks/..."
# (adresy webhooków są poufne - kto je zna, może pisać na kanał - dlatego tylko lokalnie, nie na Drive)
DYNAMIC_SECTIONS: dict[str, type] = {
    "discord": str,
}


def field_type(key: str) -> type | None:
    if key in FIELDS:
        return FIELDS[key]
    section, _, name = key.partition(".")
    return DYNAMIC_SECTIONS.get(section) if name else None


def settings_path() -> Path:
    if os.environ.get(ENV_VAR):
        return Path(os.environ[ENV_VAR])
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "rpg-chronicler" / "ustawienia.toml"


def load(path: Path | None = None) -> dict:
    """Zwraca {"sekcja.nazwa": wartość} dla poprawnych kluczy z pliku; błędne pomija z ostrzeżeniem."""
    path = path or settings_path()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[OSTRZEŻENIE] Nie można wczytać ustawień {path}: {e}")
        return {}

    values = {}
    for section, entries in data.items():
        if not isinstance(entries, dict):
            continue
        for name, value in entries.items():
            key = f"{section}.{name}"
            expected = field_type(key)
            if expected is None:
                print(f"[OSTRZEŻENIE] Nieznane ustawienie '{key}' w {path} - pomijam.")
            elif type(value) is not expected:  # bool to podklasa int - stąd dokładne porównanie typów
                print(f"[OSTRZEŻENIE] Ustawienie '{key}' w {path} ma zły typ - pomijam.")
            else:
                values[key] = value
    return values


def save(values: dict, path: Path | None = None) -> None:
    """Zapisuje ustawienia (atomowo). Wartość None usuwa klucz, czyli przywraca domyślną."""
    path = path or settings_path()
    sections: dict[str, list[str]] = {}
    dynamic = sorted(k for k in values if k not in FIELDS and field_type(k) is not None)
    for key in [*FIELDS, *dynamic]:  # stała kolejność, tylko znane klucze
        value = values.get(key)
        if value is None:
            continue
        section, name = key.split(".", 1)
        name = name if name.replace("_", "").replace("-", "").isalnum() and name.isascii() \
            else json.dumps(name, ensure_ascii=False)
        sections.setdefault(section, []).append(f"{name} = {_toml_value(value)}")

    lines = ["# Ustawienia rpg-chronicler (zmieniane z GUI). Brakujące klucze = wartości domyślne z config.py."]
    for section, entries in sections.items():
        lines += ["", f"[{section}]", *entries]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def update(changes: dict, path: Path | None = None) -> dict:
    """Wczytuje ustawienia, nakłada zmiany (None = przywróć domyślne), zapisuje i zwraca wynik."""
    values = load(path)
    values.update(changes)
    values = {k: v for k, v in values.items() if v is not None}
    save(values, path)
    return values


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # Ciąg JSON jest poprawnym podstawowym ciągiem TOML (te same sekwencje \" \\ \n \uXXXX)
    return json.dumps(str(value), ensure_ascii=False)
