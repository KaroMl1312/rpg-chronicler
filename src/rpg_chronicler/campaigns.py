"""Kampanie z pliku kampanie.toml: system RPG, opis świata, postacie graczy i słownik nazw.

Plik leży w folderze transkrypcji (TXT_DIR), więc synchronizuje się z Google Drive razem z nimi.
Klucz kampanii = prefiks nazwy sesji przed pierwszym "_" (np. "Warhammer_261015" -> "Warhammer").
Moduł używa tylko biblioteki standardowej (korzysta z niego też GUI).
"""
import datetime
import json
import os
import re
import shutil
import tomllib
from dataclasses import dataclass, field, replace

from . import config

# Kategorie słownika: klucz w TOML -> nazwa wyświetlana
GLOSSARY_CATEGORIES = {
    "npc": "Postacie niezależne (NPC)",
    "miejsca": "Miejsca",
    "przedmioty": "Przedmioty",
    "inne": "Inne nazwy (frakcje, bóstwa, pojęcia)",
}

FILE_HEADER = """\
# Kampanie RPG. Nazwa sekcji = prefiks nazwy pliku nagrania (część przed pierwszym "_"),
# np. "Warhammer_261015.m4a" -> [Warhammer]. Plik edytuje GUI (okno „Kampanie”), można też ręcznie.
#
#   system          - nazwa systemu RPG (styl i słownictwo kroniki)
#   kontekst        - opis świata/kampanii dla AI
#   postacie_graczy - postać = "gracz" (gracz opcjonalny)
#   npc, miejsca, przedmioty, inne - słownik nazw: poprawna pisownia w transkrypcji i kronikach
#   opisy           - nazwa = "krótki opis: kto to albo co to jest" (zdjęcia: folder obrazy/<kampania>/)
#   styl_obrazow    - styl obrazków generowanych przez AI (po angielsku, np. "grimdark ink and watercolor")
"""
IMAGES_DIR = "obrazy"                                  # TXT_DIR/obrazy/<kampania>/<nazwa>.<rozszerzenie>
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True)
class Campaign:
    key: str
    system: str
    context: str = ""
    player_characters: dict[str, str] = field(default_factory=dict)  # postać -> gracz ("" = nieznany)
    glossary: dict[str, tuple[str, ...]] = field(default_factory=dict)  # kategoria -> nazwy
    descriptions: dict[str, str] = field(default_factory=dict)  # nazwa (postać, BN, miejsce…) -> krótki opis
    image_style: str = ""   # styl generowanych obrazków (cechy po angielsku, bez nazw artystów i wydawców)

    def category_of(self, name: str) -> str | None:
        """Kategoria nazwy: "postacie_graczy" albo klucz słownika (npc, miejsca…); None, gdy jej nie ma."""
        wanted = name.strip().casefold()
        if any(n.casefold() == wanted for n in self.player_characters):
            return "postacie_graczy"
        return next((c for c in GLOSSARY_CATEGORIES if any(n.casefold() == wanted for n in self.names(c))), None)

    def description(self, name: str) -> str:
        """Opis nazwy (bez względu na wielkość liter); pusty, gdy go nie ma."""
        wanted = name.strip().casefold()
        return next((text for known, text in self.descriptions.items() if known.casefold() == wanted), "")

    def with_description(self, name: str, text: str) -> "Campaign":
        descriptions = {k: v for k, v in self.descriptions.items() if k.casefold() != name.strip().casefold()}
        if text.strip():
            descriptions[name.strip()] = text.strip()
        return replace(self, descriptions=descriptions)

    def names(self, category: str) -> tuple[str, ...]:
        return self.glossary.get(category, ())

    def all_names(self) -> list[str]:
        """Wszystkie nazwy (najpierw postacie graczy), bez powtórzeń - np. jako podpowiedź dla Whispera."""
        seen, result = set(), []
        for name in [*self.player_characters, *(n for c in GLOSSARY_CATEGORIES for n in self.names(c))]:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                result.append(name)
        return result

    @property
    def is_empty(self) -> bool:
        return not (self.context or self.player_characters or any(self.glossary.values()))

    def with_names(self, category: str, names) -> "Campaign":
        glossary = dict(self.glossary)
        glossary[category] = tuple(_unique(names))
        if not glossary[category]:
            del glossary[category]
        return replace(self, glossary=glossary)

    def prompt_info(self) -> str:
        """Opis kampanii dla AI: świat, postacie graczy i słownik nazw (pusty tekst, gdy nic nie ma)."""
        parts = []
        if self.context:
            parts.append(f"Opis świata i kampanii:\n{self.context}")
        if self.player_characters:
            lines = [f"- {name}" + (f" (gracz: {player})" if player else "")
                     for name, player in self.player_characters.items()]
            parts.append("Postacie graczy:\n" + "\n".join(lines))
        glossary = [f"- {label}: {', '.join(self.names(c))}" for c, label in GLOSSARY_CATEGORIES.items() if self.names(c)]
        if glossary:
            parts.append("Słownik nazw (używaj dokładnie tej pisowni; transkrypcja mogła je przekręcić):\n"
                         + "\n".join(glossary))
        return "\n\n".join(parts)


def _unique(names) -> list[str]:
    seen, result = set(), []
    for name in names:
        name = name.strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            result.append(name)
    return result


def campaigns_file() -> str:
    return os.path.join(config.TXT_DIR, config.CAMPAIGNS_FILENAME)


def campaign_key(session_name: str) -> str | None:
    """'Warhammer_261015' -> 'Warhammer'; bez '_' w nazwie -> None."""
    return session_name.split("_")[0] if "_" in session_name else None


# --- odczyt ---

_cache: dict[str, tuple[float, dict[str, Campaign]]] = {}


def load_campaigns(path: str | None = None) -> dict[str, Campaign]:
    """Kampanie z pliku (z pamięcią podręczną odświeżaną po zmianie pliku)."""
    path = path or campaigns_file()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[OSTRZEŻENIE] Błąd w pliku {path}: {e}")
        return {}
    campaigns = {key: _campaign_from_toml(key, values) for key, values in data.items() if isinstance(values, dict)}
    _cache[path] = (mtime, campaigns)
    return campaigns


def _campaign_from_toml(key: str, values: dict) -> Campaign:
    def strings(value) -> list[str]:
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    characters = values.get("postacie_graczy", {})
    if isinstance(characters, list):  # dopuszczamy też samą listę postaci
        characters = {name: "" for name in strings(characters)}
    elif not isinstance(characters, dict):
        characters = {}
    descriptions = values.get("opisy", {})
    if not isinstance(descriptions, dict):
        descriptions = {}
    return Campaign(
        key=key,
        system=str(values.get("system", key)),
        context=str(values.get("kontekst", "")).strip(),
        player_characters={str(k).strip(): str(v).strip() for k, v in characters.items() if str(k).strip()},
        glossary={category: names for category in GLOSSARY_CATEGORIES
                  if (names := tuple(_unique(strings(values.get(category, [])))))},
        descriptions={str(k).strip(): str(v).strip() for k, v in descriptions.items()
                      if str(k).strip() and str(v).strip()},
        image_style=str(values.get("styl_obrazow", "")).strip(),
    )


def campaign_for(session_name: str) -> Campaign:
    """Kampania dla sesji: z kampanie.toml, a jeśli jej tam nie ma - z prefiksu nazwy pliku."""
    key = campaign_key(session_name)
    if key is None:
        return Campaign("", "RPG")
    return load_campaigns().get(key) or default_campaign(key)


def default_campaign(key: str) -> Campaign:
    return Campaign(key, key.replace("-", " ").title())


# --- zapis ---

def save_campaigns(campaigns: dict[str, Campaign], path: str | None = None) -> None:
    """Zapisuje wszystkie kampanie (atomowo). Komentarze ręcznie dopisane w pliku nie są zachowywane."""
    path = path or campaigns_file()
    parts = [FILE_HEADER]
    for key in sorted(campaigns, key=str.casefold):
        parts.append(_campaign_to_toml(campaigns[key]))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".part"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    os.replace(tmp_path, path)
    _cache.pop(path, None)


def update_campaign(campaign: Campaign, path: str | None = None) -> None:
    campaigns = dict(load_campaigns(path))
    campaigns[campaign.key] = campaign
    save_campaigns(campaigns, path)


def _campaign_to_toml(campaign: Campaign) -> str:
    key = _toml_key(campaign.key)
    lines = [f"[{key}]", f"system = {_toml_string(campaign.system)}"]
    if campaign.context:
        lines.append(f"kontekst = {_toml_string(campaign.context)}")
    if campaign.image_style:
        lines.append(f"styl_obrazow = {_toml_string(campaign.image_style)}")
    for category in GLOSSARY_CATEGORIES:
        names = campaign.names(category)
        if names:
            items = "".join(f"    {_toml_string(n)},\n" for n in names)
            lines.append(f"{category} = [\n{items}]")
    known = {n.casefold() for n in campaign.all_names()}
    descriptions = {k: v for k, v in campaign.descriptions.items() if k.casefold() in known}  # bez usuniętych nazw
    if descriptions:
        lines.append(f"\n[{key}.opisy]")
        lines += [f"{_toml_key(name)} = {_toml_string(text)}" for name, text in descriptions.items()]
    if campaign.player_characters:
        # Podtabele na końcu: po nagłówku [X.postacie_graczy] kolejne klucze należałyby już do niej
        lines.append(f"\n[{key}.postacie_graczy]")
        lines += [f"{_toml_key(name)} = {_toml_string(player)}" for name, player in campaign.player_characters.items()]
    return "\n".join(lines) + "\n"


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _toml_string(value: str) -> str:
    """Tekst wielowierszowy jako czytelny literał '''...''' (o ile się da), reszta jako zwykły ciąg."""
    literal_ok = "'''" not in value and all(ch in "\n\t" or (ord(ch) >= 0x20 and ch != "\x7f") for ch in value)
    if "\n" in value and literal_ok:
        # Zamknięcie w osobnej linii (dopisany \n znika przy odczycie, bo opis jest przycinany)
        return "'''\n" + value + "\n'''"
    return json.dumps(value, ensure_ascii=False)


# --- zdjęcia haseł (postacie, BN-i, miejsca…) ---

def images_dir(key: str) -> str:
    """Folder zdjęć kampanii - w folderze transkrypcji, więc synchronizuje się z Drive."""
    return os.path.join(config.TXT_DIR, IMAGES_DIR, key)


def image_stem(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name.strip()).strip("_").casefold() or "hasło"


def image_path(key: str, name: str) -> str | None:
    """Zdjęcie hasła albo None."""
    for ext in IMAGE_EXTENSIONS:
        path = os.path.join(images_dir(key), image_stem(name) + ext)
        if os.path.isfile(path):
            return path
    return None


def remove_image(key: str, name: str) -> None:
    while (path := image_path(key, name)) is not None:
        os.remove(path)


def set_image(key: str, name: str, source: str) -> str:
    """Kopiuje zdjęcie do folderu kampanii (zastępuje poprzednie); zwraca nową ścieżkę. Rzuca ValueError/OSError."""
    ext = os.path.splitext(source)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Nieobsługiwany format zdjęcia ({ext or 'brak rozszerzenia'}) - użyj JPG, PNG albo WebP.")
    os.makedirs(images_dir(key), exist_ok=True)
    target = os.path.join(images_dir(key), image_stem(name) + ext)
    tmp = target + ".part"
    shutil.copyfile(source, tmp)
    remove_image(key, name)
    os.replace(tmp, target)
    return target


# --- kolejność sesji ---

DATE_PATTERNS = [
    (re.compile(r"_(\d{1,2})_(\d{1,2})_(\d{4})$"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),  # DD_MM_RRRR
    (re.compile(r"_(\d{2})(\d{2})(\d{2})$"), lambda m: (2000 + int(m[1]), int(m[2]), int(m[3]))),  # RRMMDD
]


def session_date(session_name: str) -> datetime.date | None:
    """Data sesji z nazwy: 'Warhammer_261015' (RRMMDD) albo 'Fallout_16_09_2026' (DD_MM_RRRR)."""
    for pattern, parts in DATE_PATTERNS:
        match = pattern.search(session_name)
        if match:
            try:
                return datetime.date(*parts(match))
            except ValueError:
                return None
    return None
