"""Usuwanie kroniki albo sesji (`delete`, menu „⋯” nad sesją w GUI) - lokalnie i na Google Drive.

Trzy zakresy:
- KRONIKA: kronika i wszystko z niej (skrót, cytaty, PDF, zapowiedź, stan wysyłki, lista wydarzeń);
  transkrypcja albo notatki zostają - sesja wraca do „czeka na kronikę”,
- OD_NOWA: wszystko poza nagraniem (transkrypcja, mówcy, odciski głosu, kronika…) - sesja od transkrypcji,
- SESJA: całe wymazanie, razem z nagraniem (i oryginałem sprzed przycięcia ciszy).

Nic nie znika od razu na zawsze: lokalne pliki trafiają do kosza aplikacji (~/.local/share/rpg-chronicler/kosz,
`delete --undo` przywraca najnowsze usunięcie, wpisy starsze niż TRASH_DAYS są czyszczone), a na Drive -
do kosza Google Drive (rclone, storage/drive.py). Najpierw Drive: gdyby tam się nie udało, a lokalnie tak,
`sync` pobrałby pliki z powrotem. Pamięć podręczna sesji (listy wydarzeń, poprzednie wersje, analiza ciszy)
jest kasowana - da się ją odtworzyć. Encyklopedii, dzienników i stanu kampanii nie ruszamy (są wspólne dla
kampanii) - `campaign_warnings` mówi, co warto odświeżyć. Tylko stdlib (GUI pokazuje plan przed potwierdzeniem).
"""
import datetime
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..campaign_tools import encyclopedia, memory
from .. import session as _session
from .archive import belongs_to
from .backfill import existing_diaries
from ..campaigns import campaign_key

CHRONICLE, RESTART, SESSION = "kronika", "od-nowa", "sesja"
SCOPES = (CHRONICLE, RESTART, SESSION)
SCOPE_LABELS = {CHRONICLE: "kronika", RESTART: "wszystko poza nagraniem", SESSION: "cała sesja z nagraniem"}
ORIGINALS_DIR = "oryginaly"     # audio_trim: nagrania sprzed przycięcia ciszy
TRASH_DAYS = 30
MANIFEST = "usuniete.json"


class DeletionError(Exception):
    pass


@dataclass(frozen=True)
class Plan:
    name: str
    scope: str
    files: tuple[str, ...]          # lokalne pliki danych (trafią do kosza)
    caches: tuple[str, ...]         # pamięć podręczna sesji (kasowana)

    @property
    def remote_kinds(self) -> tuple[str, ...]:
        """Foldery na Drive do wyczyszczenia: „audio”, „txt”, „summary” (jak w storage/drive.py)."""
        return {CHRONICLE: ("summary",), RESTART: ("txt", "summary"), SESSION: ("audio", "txt", "summary")}[self.scope]


def _cache_home() -> str:
    return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


def _files_in(directory: str, name: str, in_summary: bool) -> list[str]:
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return []
    return [os.path.join(directory, f) for f in entries
            if belongs_to(f, name, in_summary) and os.path.isfile(os.path.join(directory, f))]


def plan(name: str, scope: str) -> Plan:
    """Co zniknie. Rzuca DeletionError, gdy zakres nie pasuje do sesji albo nie ma czego usuwać."""
    if scope not in SCOPES:
        raise DeletionError(f"Nieznany zakres usuwania: {scope}")
    session = next((s for s in _session.list_sessions() if s.name == name), None)
    if session is None:
        raise DeletionError(f"Nie znaleziono sesji '{name}'. Sprawdź listę: rpg-chronicler status")
    if scope == RESTART and session.audio_path is None:
        raise DeletionError(f"Sesja {name} nie ma nagrania - „od nowa” nie ma od czego zacząć. "
                            f"Usuń kronikę albo całą sesję.")
    files = _files_in(_session.SUMMARY_DIR, name, True)
    if scope in (RESTART, SESSION):
        files += _files_in(_session.TXT_DIR, name, False)
    if scope == SESSION:
        files += _files_in(_session.AUDIO_DIR, name, False)
        files += _files_in(os.path.join(_session.AUDIO_DIR, ORIGINALS_DIR), name, False)

    cache = os.path.join(_cache_home(), "rpg-chronicler")
    caches = [os.path.join(cache, "wydarzenia", name), os.path.join(cache, "kroniki-poprzednie", name)]
    if scope in (RESTART, SESSION):
        caches.append(os.path.join(cache, "transkrypcje-poprzednie", name))
    if scope == SESSION:
        caches.append(os.path.join(cache, "cisza", f"{name}.json"))
    caches = [c for c in caches if os.path.exists(c)]
    if not files:
        what = "kroniki" if scope == CHRONICLE else "plików"
        raise DeletionError(f"Sesja {name} nie ma lokalnie {what} do usunięcia.")
    return Plan(name, scope, tuple(files), tuple(caches))


def describe(p: Plan) -> str:
    """Lista plików do okna potwierdzenia (nazwy plików, pogrupowane wg folderu)."""
    lines = []
    for directory in dict.fromkeys(os.path.dirname(f) for f in p.files):
        names = [os.path.basename(f) for f in p.files if os.path.dirname(f) == directory]
        lines.append(f"{os.path.basename(directory)}/: {', '.join(names)}")
    return "\n".join(lines)


# --- kosz aplikacji ---

def trash_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(data_home) / "rpg-chronicler" / "kosz"


def _entries(name: str | None = None) -> list[Path]:
    """Wpisy kosza (od najnowszego), opcjonalnie tylko jednej sesji."""
    try:
        entries = [e for e in trash_dir().iterdir() if (e / MANIFEST).is_file()]
    except OSError:
        return []
    if name is not None:
        entries = [e for e in entries if e.name.rsplit("__", 1)[0] == name]
    return sorted(entries, key=lambda e: e.name.rsplit("__", 1)[-1], reverse=True)


def purge_old(days: int = TRASH_DAYS, now: datetime.datetime | None = None) -> int:
    """Kasuje z kosza usunięcia starsze niż `days` dni; zwraca ich liczbę."""
    limit = (now or datetime.datetime.now()) - datetime.timedelta(days=days)
    removed = 0
    for entry in _entries():
        try:
            when = datetime.datetime.strptime(entry.name.rsplit("__", 1)[-1], "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if when < limit:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def delete_local(p: Plan, now: datetime.datetime | None = None) -> Path:
    """Przenosi pliki do kosza (z listą oryginalnych ścieżek) i kasuje pamięć podręczną. Zwraca wpis kosza."""
    purge_old(now=now)
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    entry = trash_dir() / f"{p.name}__{stamp}"
    entry.mkdir(parents=True, exist_ok=False)
    moved = []
    for index, path in enumerate(p.files):
        target = entry / f"{index:03d}-{os.path.basename(path)}"
        shutil.move(path, target)
        moved.append({"z": path, "w": target.name})
        (entry / MANIFEST).write_text(json.dumps({"sesja": p.name, "zakres": p.scope, "pliki": moved},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    for cache in p.caches:
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)
        else:
            try:
                os.remove(cache)
            except OSError:
                pass
    return entry


def restore(name: str) -> list[str]:
    """Przywraca najnowsze usunięcie sesji z kosza aplikacji; zwraca przywrócone ścieżki."""
    entries = _entries(name)
    if not entries:
        raise DeletionError(f"W koszu nie ma usuniętych plików sesji {name}.")
    entry = entries[0]
    manifest = json.loads((entry / MANIFEST).read_text(encoding="utf-8"))
    clashes = [item["z"] for item in manifest["pliki"] if os.path.exists(item["z"])]
    if clashes:
        raise DeletionError("Nie przywracam - te pliki już istnieją: " + ", ".join(clashes))
    restored = []
    for item in manifest["pliki"]:
        os.makedirs(os.path.dirname(item["z"]), exist_ok=True)
        shutil.move(entry / item["w"], item["z"])
        restored.append(item["z"])
    shutil.rmtree(entry, ignore_errors=True)
    return restored


# --- co jeszcze pamięta usuniętą sesję ---

def campaign_warnings(name: str) -> list[str]:
    """Materiały kampanii, które wciąż mogą opisywać usuniętą sesję (do odświeżenia ręcznie)."""
    key = campaign_key(name)
    if key is None:
        return []
    warnings = []
    state = memory.load_state(key)
    if state is not None and state.session == name:
        warnings.append(f"Stan kampanii {key} zapisano po tej sesji - zbuduj go od nowa: "
                        f"rpg-chronicler memory {key} --rebuild (GUI: Kampanie → Pamięć kampanii).")
    proposal = memory.load_proposal(key)
    if proposal is not None and proposal.session == name:
        warnings.append(f"Propozycja stanu kampanii {key} pochodzi z tej sesji - odrzuć ją albo zbuduj od nowa.")
    if os.path.exists(encyclopedia.markdown_path(key)):
        warnings.append(f"Encyklopedia kampanii {key} może opisywać tę sesję - odśwież ją: "
                        f"rpg-chronicler encyclopedia {key}.")
    characters = [character for character, _path in existing_diaries(key)]
    if characters:
        warnings.append(f"Dzienniki postaci ({', '.join(characters)}) mogą mieć wpis o tej sesji - odśwież je: "
                        f"rpg-chronicler diary {key} POSTAĆ.")
    return warnings
