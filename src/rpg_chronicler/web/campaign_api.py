"""Dane nowego okna do zakładki Kampanie (etap 3): kampania, słownik, pamięć, przed sesją, dokumenty, obrazki.

Jak api.py - bez HTTP, słowniki gotowe do JSON-a; logika ta sama co w gui/campaigns_view.py i gui/entry_page.py.
Serwer obsługuje zapytania w wątkach, więc zmiany kampanie.toml (odczyt - zmiana - zapis) idą przez jeden zamek.
"""
import base64
import binascii
import datetime
import os
import tempfile
import threading
import tomllib
from dataclasses import replace

from .. import campaigns, chronicle, envfile, notes
from ..campaign_tools import ask, diary, encyclopedia, glossary, images, memory, prep
from ..campaigns import GLOSSARY_CATEGORIES, IMAGE_EXTENSIONS, Campaign, campaign_key, image_path
from ..session import list_sessions
from .api import markdown_html

CATEGORY_LABELS = {glossary.PLAYER_CHARACTERS: "Postacie graczy", **GLOSSARY_CATEGORIES}
ASK_HISTORY_SHOWN = 5                  # ostatnie pytania widoczne w oknie (historia ma ich więcej)
IMAGE_LIMIT = 15 * 1024 * 1024         # bajtów zdjęcia wczytywanego z okna
_lock = threading.Lock()


# --- kampanie ----------------------------------------------------------------------------------------

def _prefixes() -> set[str]:
    return {k for s in list_sessions() if (k := campaign_key(s.name))}


def _campaign(key: str) -> Campaign:
    """Kampania z pliku albo z prefiksu nagrań. Klucz trafia do ścieżek plików, więc tylko znane."""
    known = campaigns.load_campaigns()
    if key in known:
        return known[key]
    if key and key in _prefixes():
        return campaigns.default_campaign(key)
    raise ValueError(f"Nie ma kampanii {key}")


def _save(campaign: Campaign) -> None:
    """Zapis kampanii - ale nie do pliku z błędem składni: load_campaigns widzi go jako pusty, więc zapis
    skasowałby wszystkie pozostałe kampanie. Wołać z _lock."""
    path = campaigns.campaigns_file()
    try:
        with open(path, "rb") as f:
            tomllib.load(f)
    except FileNotFoundError:
        pass
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"Nie zapisano: plik {path} ma błąd ({e}). Popraw go ręcznie.") from e
    campaigns.update_campaign(campaign)


def _entry_name(campaign: Campaign, name: str) -> str:
    """Nazwa hasła dokładnie jak w słowniku; ValueError, gdy jej tam nie ma."""
    wanted = str(name).strip().casefold()
    found = next((n for n in campaign.all_names() if n.casefold() == wanted), None)
    if found is None:
        raise ValueError(f"Nie ma hasła „{name}” w słowniku kampanii {campaign.key}")
    return found


def campaign_list() -> dict:
    items = []
    for key, campaign in sorted(campaigns.load_campaigns().items(), key=lambda kv: kv[0].casefold()):
        items.append({"key": key, "system": campaign.system,
                      "proposals": glossary.count_proposals(glossary.pending_for(campaign)),
                      "new_state": memory.load_proposal(key) is not None})
    missing = sorted(_prefixes() - {i["key"] for i in items}, key=str.casefold)
    return {"campaigns": items, "missing": missing}


def create(key: str) -> dict:
    key = str(key).strip()
    if not notes.NAME_RE.match(key):
        raise ValueError("Podaj prefiks nazw nagrań bez spacji i „_”, np. Warhammer")
    with _lock:
        if key not in campaigns.load_campaigns():
            _save(campaigns.default_campaign(key))
    return {"key": key}


# --- jedna kampania ------------------------------------------------------------------------------------

def _version(path: str | None) -> int | None:
    """Znacznik wersji pliku do adresu obrazka (zmienione zdjęcie nie może zostać z pamięci okna)."""
    try:
        return os.stat(path).st_mtime_ns if path else None
    except OSError:
        return None


def _file_date(path: str) -> str:
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d.%m.%Y %H:%M")
    except OSError:
        return ""


def _entry(campaign: Campaign, name: str) -> dict:
    path = image_path(campaign.key, name)
    # wersja jako tekst: nanosekundy nie mieszczą się w liczbach JavaScriptu
    return {"name": name, "description": campaign.description(name), "image": str(_version(path) or "")}


def _prep_status(path: str, key: str, sessions) -> str:
    after, text = prep.read(path)
    if not text:
        return "jeszcze nie napisane"
    if prep.is_current(path, key, sessions):
        return f"po sesji {after}"
    latest = prep.latest_session(key, sessions)
    return f"nieaktualne - po sesji {after}, a jest już kronika {latest.name if latest else '?'}"


def _state(state: memory.State | None) -> dict | None:
    return {"text": state.text, "session": state.session} if state is not None else None


def _document(path: str) -> dict:
    exists = os.path.exists(path)
    return {"path": path if exists else "", "name": os.path.basename(path), "date": _file_date(path) if exists else ""}


def detail(key: str) -> dict:
    campaign = _campaign(key)
    sessions = list_sessions()
    pending = glossary.pending_for(campaign)
    names = campaign.all_names()
    recap, ideas = prep.recap_path(key), prep.ideas_path(key)
    recap_text, ideas_text = prep.read(recap)[1], prep.read(ideas)[1]
    return {
        "key": key, "system": campaign.system, "context": campaign.context, "image_style": campaign.image_style,
        "file": campaigns.campaigns_file(), "webhook": bool(chronicle.webhook_for(key)),
        "state": _state(memory.load_state(key)), "proposal": _state(memory.load_proposal(key)),
        # słownik
        "proposals": {"count": glossary.count_proposals(pending),
                      "groups": [{"category": c, "label": CATEGORY_LABELS[c], "names": pending[c]}
                                 for c in glossary.CATEGORIES if pending.get(c)],
                      "description": pending.get(glossary.DESCRIPTION) or ""},
        "described": sum(1 for n in names if campaign.description(n)), "names_count": len(names),
        "characters": [{**_entry(campaign, n), "player": p} for n, p in campaign.player_characters.items()],
        "categories": [{"key": c, "label": label, "names": [_entry(campaign, n) for n in campaign.names(c)]}
                       for c, label in GLOSSARY_CATEGORIES.items()],
        # przed sesją
        "has_chronicles": prep.latest_session(key, sessions) is not None,
        "recap": {"title": f"{prep.RECAP_TITLE}…", "status": _prep_status(recap, key, sessions), "text": recap_text},
        "ideas": {"title": prep.IDEAS_TITLE, "status": _prep_status(ideas, key, sessions), "count": prep.IDEAS_COUNT,
                  "html": markdown_html(ideas_text) if ideas_text else ""},
        "gm_notes": {"status": _prep_status(prep.gm_notes_path(key), key, sessions),
                     **_document(prep.gm_notes_pdf_path(key))},
        "history": [{"question": a.question, "html": markdown_html(a.answer), "sessions": a.sessions,
                     "asked": a.asked, "when": a.asked.replace("T", " ")}
                    for a in ask.load_history(key)[:ASK_HISTORY_SHOWN]],
        # dokumenty
        "encyclopedia": _document(encyclopedia.pdf_path(key)),
        "diaries": [{"character": n, **_document(diary.pdf_path(key, n))} for n in campaign.player_characters],
    }


# --- zmiany kampanii (kampanie.toml) -------------------------------------------------------------------

def _set_text(field_name: str, required: bool = False):
    def change(campaign: Campaign, body: dict) -> Campaign:
        value = str(body.get("value", "")).strip()
        if required and not value:
            raise ValueError("To pole nie może być puste")
        return replace(campaign, **{field_name: value})
    return change


def _add_character(campaign: Campaign, body: dict) -> Campaign:
    name, _, player = str(body.get("value", "")).partition("=")   # „Fen” albo „Fen = Ania”
    name, player = name.strip(), player.strip()
    if not name:
        raise ValueError("Podaj imię postaci")
    characters = dict(campaign.player_characters)
    characters[name] = player or characters.get(name, "")
    return replace(campaign, player_characters=characters)


def _set_player(campaign: Campaign, body: dict) -> Campaign:
    if body["name"] not in campaign.player_characters:
        raise ValueError(f"Nie ma postaci {body['name']}")
    return replace(campaign, player_characters={**campaign.player_characters,
                                                body["name"]: str(body.get("value", "")).strip()})


def _remove_character(campaign: Campaign, body: dict) -> Campaign:
    return replace(campaign, player_characters={k: v for k, v in campaign.player_characters.items()
                                                if k != body["name"]})


def _category(body: dict) -> str:
    if body["category"] not in GLOSSARY_CATEGORIES:
        raise ValueError(f"Nieznana kategoria: {body['category']}")
    return body["category"]


def _add_names(campaign: Campaign, body: dict) -> Campaign:
    new = [n.strip() for n in str(body.get("value", "")).split(",") if n.strip()]
    if not new:
        raise ValueError("Podaj nazwę")
    category = _category(body)
    return campaign.with_names(category, [*campaign.names(category), *new])


def _remove_name(campaign: Campaign, body: dict) -> Campaign:
    category = _category(body)
    return campaign.with_names(category, [n for n in campaign.names(category) if n != body["name"]])


def _set_description(campaign: Campaign, body: dict) -> Campaign:
    return campaign.with_description(_entry_name(campaign, body["name"]), str(body.get("value", "")))


CHANGES = {
    "system": _set_text("system", required=True), "context": _set_text("context"),
    "image_style": _set_text("image_style"), "description": _set_description,
    "add_character": _add_character, "set_player": _set_player, "remove_character": _remove_character,
    "add_names": _add_names, "remove_name": _remove_name,
}


def change(key: str, what: str, body: dict) -> dict:
    if what not in CHANGES:
        raise ValueError(f"Nieznana zmiana: {what}")
    with _lock:
        _save(CHANGES[what](_campaign(key), body))
    return {"ok": True}


# --- propozycje słownika ---------------------------------------------------------------------------------

def resolve_proposals(key: str, shown: dict, accepted: dict) -> dict:
    """`shown` - propozycje, które użytkownik widział (wszystkie znikają z oczekujących), `accepted` - zaznaczone."""
    with _lock:
        campaign = _campaign(key)
        pending = glossary.pending_for(campaign)

        def only_pending(chosen: dict) -> dict:
            result = {c: [n for n in pending.get(c, []) if n in set(chosen.get(c, []))] for c in glossary.CATEGORIES}
            result = {c: names for c, names in result.items() if names}
            if chosen.get(glossary.DESCRIPTION) and pending.get(glossary.DESCRIPTION):
                result[glossary.DESCRIPTION] = pending[glossary.DESCRIPTION]
            return result

        taken = only_pending(accepted)
        if taken:
            _save(glossary.accept(campaign, taken))
        glossary.remove_from_pending(key, only_pending(shown))
    return {"added": sum(len(v) if isinstance(v, list) else 1 for v in taken.values())}


# --- pamięć kampanii ---------------------------------------------------------------------------------------

def memory_action(key: str, action: str, text: str, session: str | None) -> dict:
    """`session` - po której sesji był stan widoczny w oknie. Zadanie mogło go w międzyczasie podmienić: wtedy
    tekst sprzed zmiany dostałby nagłówek nowszej sesji, więc odmawiamy."""
    _campaign(key)
    with _lock:
        shown = memory.load_state(key) if action == "save" else memory.load_proposal(key)
        if action in ("accept", "reject") and shown is None:
            raise ValueError("Nie ma już propozycji stanu kampanii")
        if shown is not None and shown.session != session:
            raise ValueError("Stan kampanii zmienił się w międzyczasie - sprawdź nową wersję")
        if action == "accept":
            memory.accept_proposal(key, text)
        elif action == "reject":
            memory.discard_proposal(key)
        elif action == "save":
            memory.save_state(key, text, shown.session if shown is not None else None)
        else:
            raise ValueError(f"Nieznana czynność: {action}")
    return {"ok": True}


# --- pytania, Discord --------------------------------------------------------------------------------------

def forget_answer(key: str, question: str, asked: str) -> dict:
    """Po treści i czasie, nie po numerze - nowa odpowiedź mogła przesunąć listę."""
    _campaign(key)
    with _lock:
        for index, item in enumerate(ask.load_history(key)):
            if item.question == question and item.asked == asked:
                ask.remove_from_history(key, index)
                break
    return {"ok": True}


def remove_webhook(key: str) -> dict:
    _campaign(key)
    chronicle.set_webhook(key, None)
    return {"ok": True}


# --- hasło: opis, zdjęcie, obrazek od AI -------------------------------------------------------------------

def entry(key: str, name: str) -> dict:
    campaign = _campaign(key)
    name = _entry_name(campaign, name)
    proposal = images.candidate(key, name)
    category = campaign.category_of(name) or ""
    return {**_entry(campaign, name),
            "category": "Postać gracza" if category == glossary.PLAYER_CHARACTERS else CATEGORY_LABELS.get(category, ""),
            "proposal": str(_version(proposal) or ""), "proposal_prompt": images.prompt_for(key, name),
            "hints": images.last_hints(key, name),
            "can_generate": bool(envfile.get("CLOUDFLARE_ACCOUNT_ID") and envfile.get("CLOUDFLARE_API_TOKEN"))}


def image_file(key: str, name: str, proposal: bool) -> str:
    campaign = _campaign(key)
    name = _entry_name(campaign, name)
    path = images.candidate(key, name) if proposal else image_path(key, name)
    if path is None:
        raise ValueError("Brak zdjęcia")
    return path


def upload_image(key: str, name: str, filename: str, data: str) -> dict:
    """Zdjęcie wybrane w oknie (treść pliku w base64)."""
    name = _entry_name(_campaign(key), name)
    ext = os.path.splitext(str(filename))[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Nieobsługiwany format zdjęcia ({ext or 'brak rozszerzenia'}) - użyj JPG, PNG albo WebP.")
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("Nie można odczytać zdjęcia") from e
    if not content or len(content) > IMAGE_LIMIT:
        raise ValueError(f"Zdjęcie może mieć najwyżej {IMAGE_LIMIT // 2 ** 20} MB")
    fd, tmp = tempfile.mkstemp(suffix=ext, prefix="rpg-chronicler-zdjecie-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        with _lock:
            campaigns.set_image(key, name, tmp)
    finally:
        os.unlink(tmp)
    return {"ok": True}


def image_action(key: str, name: str, action: str) -> dict:
    name = _entry_name(_campaign(key), name)
    with _lock:
        if action == "remove":
            campaigns.remove_image(key, name)
        elif action == "keep":
            try:
                images.keep_candidate(key, name)
            except images.ImageError as e:
                raise ValueError(str(e)) from e
        elif action == "discard":
            images.discard_candidates(key, name)
        else:
            raise ValueError(f"Nieznana czynność: {action}")
    return {"ok": True}
