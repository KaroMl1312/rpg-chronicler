"""Prompty zmienione przez użytkownika: lokalnie obok ustawień (`<folder ustawień>/prompty/<nazwa>.md`).

Szablony są dla `str.format`, więc dosłowne klamry mają w pliku postać `{{`/`}}`. Użytkownik widzi i edytuje
tekst z pojedynczymi klamrami: `to_display` je odpodwaja, a `to_template` podwaja wszystkie poza polami
domyślnego szablonu ({source}, {system_name}…). Tylko stdlib - używa tego też GUI.
"""
import hashlib
import json
import os
import re
import string
from importlib.resources import files
from pathlib import Path

CACHE_MARK = "---8<---"
META_FILE = "zmiany.json"   # nazwa -> {"base": sha1 domyślnego szablonu w chwili zapisu}
NAME_RE = re.compile(r"^[a-z_]+$")


class PromptError(ValueError):
    pass


def prompts_dir() -> Path:
    from ..settings import settings_path
    return settings_path().parent / "prompty"


def names() -> list[str]:
    return sorted(p.name[:-3] for p in files(__package__).iterdir() if p.name.endswith(".md"))


def _check(name: str) -> None:
    if not NAME_RE.match(name) or name not in names():
        raise PromptError(f"Nie ma promptu „{name}”")


def default(name: str) -> str:
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def fields(template: str) -> list[str]:
    """Pola {nazwa} szablonu w kolejności pierwszego wystąpienia."""
    found = []
    for _, field, _, _ in string.Formatter().parse(template):
        if field and field not in found:
            found.append(field)
    return found


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _path(name: str) -> Path:
    return prompts_dir() / f"{name}.md"


def _meta() -> dict:
    try:
        with open(prompts_dir() / META_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def to_display(template: str) -> str:
    return template.replace("{{", "{").replace("}}", "}")


def to_template(text: str, known: list[str]) -> str:
    escaped = text.replace("{", "{{").replace("}", "}}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: "{" + m[1] + "}" if m[1] in known else m[0], escaped)


def load(name: str) -> str | None:
    """Zmieniony szablon albo None (brak zmian lub zepsuty plik - wtedy domyślny)."""
    path = _path(name)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        text.format(**{f: "" for f in fields(default(name))})
    except (OSError, ValueError, KeyError, IndexError) as e:
        print(f"[OSTRZEŻENIE] Zmieniony prompt {path} jest uszkodzony ({e}) - używam domyślnego.")
        return None
    return text


def template(name: str) -> str:
    """Szablon używany przez program: zmieniony przez użytkownika albo domyślny."""
    return load(name) or default(name)


def warnings(name: str, text: str) -> list[str]:
    """Uwagi do tekstu promptu (z pojedynczymi klamrami) - nie blokują zapisu."""
    from .catalog import field_description
    known = fields(default(name))
    result = []
    for field in known:
        if "{" + field + "}" not in text:
            result.append(f"Brak pola {{{field}}} - AI nie dostanie: {field_description(field)}.")
    for word in sorted(set(re.findall(r"\{(\w+)\}", text)) - set(known)):
        result.append(f"{{{word}}} nie jest polem tego promptu - zostanie wysłane dosłownie.")
    if CACHE_MARK in default(name) and f"\n{CACHE_MARK}\n" not in f"\n{text}\n":
        result.append(f"Brak linii {CACHE_MARK} - prompt zadziała, ale bez tańszego powtórnego czytania (cache API).")
    return result


def save(name: str, text: str) -> list[str]:
    """Zapisuje zmieniony prompt (tekst z pojedynczymi klamrami); zwraca uwagi. Tekst = domyślny → usuwa zmianę."""
    _check(name)
    text = text.replace("\r\n", "\n")
    if not text.strip():
        raise PromptError("Prompt nie może być pusty")
    base = default(name)
    result = to_template(text, fields(base))
    if result == base:
        reset(name)
        return []
    _write_atomic(_path(name), result)
    meta = _meta()
    meta[name] = {"base": _sha(base)}
    _write_atomic(prompts_dir() / META_FILE, json.dumps(meta, ensure_ascii=False, indent=2))
    return warnings(name, text)


def reset(name: str) -> None:
    _check(name)
    _path(name).unlink(missing_ok=True)
    meta = _meta()
    if meta.pop(name, None) is not None:
        _write_atomic(prompts_dir() / META_FILE, json.dumps(meta, ensure_ascii=False, indent=2))


def status(name: str) -> dict:
    """Czy prompt jest zmieniony i czy domyślny zmienił się od chwili zapisu (nowa wersja programu)."""
    changed = load(name) is not None
    base = _meta().get(name, {}).get("base") if changed else None
    return {"changed": changed, "default_updated": bool(changed and base and base != _sha(default(name)))}
