"""Obrazki haseł kampanii od AI (`image KAMPANIA NAZWA`, przycisk „Wygeneruj obrazek” na stronie hasła).

Przebieg: LLM pisze z opisu hasła i stylu kampanii prompt po angielsku (`prompts/image_prompt.md`), a model
obrazkowy go rysuje. Dostawca: Cloudflare Workers AI (FLUX.1 [schnell], darmowy limit dzienny; klucze
CLOUDFLARE_ACCOUNT_ID i CLOUDFLARE_API_TOKEN z .env). Styl kampanii (`Campaign.image_style`) przy pierwszym
obrazku proponuje LLM (`prompts/image_style.md`: cechy, bez nazw artystów i wydawców) i zapisuje w kampanii.
Wynik to **propozycja** w ~/.cache/rpg-chronicler/obrazki/<kampania>/ - zdjęciem hasła staje się dopiero po
„Zachowaj” (`keep_candidate` → `campaigns.set_image`) albo od razu z `image --zachowaj`.
Moduł bez zależności zewnętrznych (urllib; GUI czyta propozycje); LLM tylko w funkcjach z klientem.
"""
import base64
import datetime
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from .campaigns import Campaign, image_path, image_stem, set_image, update_campaign

CATEGORY_LABELS = {"postacie_graczy": "postać gracza", "npc": "postać niezależna", "miejsca": "miejsce",
                   "przedmioty": "przedmiot", "inne": "frakcja, bóstwo albo pojęcie"}
API_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
TIMEOUT = 120
PROMPT_LIMIT = 2048   # znaków promptu dla FLUX w Workers AI


class ImageError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class CloudflareImages:
    name = "Cloudflare FLUX"

    def __init__(self, account_id: str | None = None, token: str | None = None, model: str = config.IMAGE_MODEL):
        self.account_id = account_id if account_id is not None else config.CLOUDFLARE_ACCOUNT_ID
        self.token = token if token is not None else config.CLOUDFLARE_API_TOKEN
        self.model = model
        if not self.account_id or not self.token:
            raise ImageError("Brak CLOUDFLARE_ACCOUNT_ID albo CLOUDFLARE_API_TOKEN w .env - obrazki generuje "
                             "Cloudflare Workers AI (darmowe konto, token z uprawnieniem Workers AI).")

    def generate(self, prompt: str, steps: int = config.IMAGE_STEPS) -> bytes:
        """Obrazek (JPEG) dla promptu. Rzuca ImageError (retryable przy limitach i błędach serwera)."""
        body = json.dumps({"prompt": prompt[:PROMPT_LIMIT], "steps": steps}).encode("utf-8")
        request = urllib.request.Request(API_URL.format(account=self.account_id, model=self.model), data=body,
                                         headers={"Authorization": f"Bearer {self.token}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as e:
            try:
                errors = [err.get("message", "") for err in json.loads(e.read()).get("errors", [])]
            except (ValueError, AttributeError):
                errors = []
            hint = {401: " (zły token?)", 403: " (token bez uprawnienia Workers AI?)",
                    429: " (dzienny limit darmowych obrazków - spróbuj jutro)"}.get(e.code, "")
            if any("NSFW" in err for err in errors):
                hint = " (filtr treści odrzucił opis - spróbuj ponownie albo popraw opis hasła)"
            raise ImageError(f"Cloudflare: HTTP {e.code}{hint} {'; '.join(errors)}".strip(),
                             retryable=e.code == 429 or e.code >= 500) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ImageError(f"Cloudflare: brak połączenia ({e})", retryable=True) from e
        image = (data.get("result") or {}).get("image") if isinstance(data, dict) else None
        if not image:
            raise ImageError("Cloudflare nie zwrócił obrazka.")
        return base64.b64decode(image)


def get_image_client():
    return CloudflareImages()


# --- propozycje (przed „Zachowaj”) ---

def candidates_dir(key: str) -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "obrazki" / key


def candidate(key: str, name: str) -> str | None:
    """Najnowsza propozycja obrazka hasła (nowsza niż jego zdjęcie) albo None."""
    try:
        found = sorted(candidates_dir(key).glob(f"{image_stem(name)}__*.jpg"), reverse=True)
    except OSError:
        return None
    if not found:
        return None
    current = image_path(key, name)
    if current is not None and os.path.getmtime(current) >= found[0].stat().st_mtime:
        return None
    return str(found[0])


def prompt_for(key: str, name: str) -> str:
    """Prompt obrazka zapisany obok propozycji (do podglądu w GUI)."""
    path = candidate(key, name)
    try:
        return Path(path).with_suffix(".txt").read_text(encoding="utf-8") if path else ""
    except OSError:
        return ""


def discard_candidates(key: str, name: str) -> None:
    for path in candidates_dir(key).glob(f"{image_stem(name)}__*"):
        path.unlink(missing_ok=True)


def keep_candidate(key: str, name: str) -> str:
    """Propozycja staje się zdjęciem hasła (obrazy/<kampania>/); zwraca ścieżkę. Rzuca ImageError."""
    path = candidate(key, name)
    if path is None:
        raise ImageError(f"Brak propozycji obrazka dla „{name}”.")
    saved = set_image(key, name, path)
    discard_candidates(key, name)
    return saved


# --- generowanie ---

def ensure_style(llm, campaign: Campaign) -> Campaign:
    """Kampania ze stylem obrazków (gdy go nie ma - propozycja LLM, zapisana w kampanie.toml)."""
    if campaign.image_style:
        return campaign
    from dataclasses import replace

    from .llm import generate, with_retry
    from .prompts import render
    info = f"\n\nO kampanii:\n{campaign.context}" if campaign.context else ""
    prompt = render("image_style", system_name=campaign.system, campaign_info=info)
    print(f"[{llm.name}] Styl obrazków kampanii {campaign.key}...")
    style = " ".join(with_retry(lambda: generate(llm, prompt), f"styl obrazków {campaign.key}").split())
    campaign = replace(campaign, image_style=style.strip().strip('"„”'))
    update_campaign(campaign)
    print(f"[INFO] Styl obrazków kampanii {campaign.key}: {campaign.image_style} (zmienisz go w zakładce Kampanie)")
    return campaign


def hints_path(key: str, name: str) -> Path:
    return candidates_dir(key) / f"{image_stem(name)}.wskazowki.txt"


def last_hints(key: str, name: str) -> str:
    """Ostatnie wskazówki użytkownika do obrazka hasła (GUI wpisuje je w okienko przy kolejnej próbie)."""
    try:
        return hints_path(key, name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _save_hints(key: str, name: str, hints: str) -> None:
    path = hints_path(key, name)
    if hints.strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(hints.strip() + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def image_prompt(llm, campaign: Campaign, name: str, hints: str = "") -> str:
    """Prompt po angielsku z opisu hasła, stylu kampanii i wskazówek użytkownika (po polsku - LLM tłumaczy)."""
    from .llm import generate, with_retry
    from .prompts import render
    category = CATEGORY_LABELS.get(campaign.category_of(name) or "", "hasło z kampanii")
    info = f"Świat: {campaign.context}\n" if campaign.context else ""
    prompt = render("image_prompt", system_name=campaign.system, entry=name, category=category,
                    description=campaign.description(name) or "(brak - wywnioskuj z nazwy i świata)",
                    campaign_info=info, style=campaign.image_style,
                    user_hints=f"Wskazówki użytkownika (najważniejsze): {' '.join(hints.split())}\n"
                    if hints.strip() else "")
    print(f"[{llm.name}] Opis obrazka: {name}" + (f" (wskazówki: {' '.join(hints.split())})" if hints.strip() else "")
          + "...")
    return " ".join(with_retry(lambda: generate(llm, prompt), f"prompt obrazka {name}").split())


def generate_candidate(llm, images, campaign: Campaign, name: str, hints: str = "") -> str:
    """Propozycja obrazka hasła (JPEG w cache + prompt w .txt); zwraca ścieżkę. Rzuca LLMError/ImageError.

    `hints` - dodatkowe wskazówki użytkownika po polsku (zapamiętane do następnej próby)."""
    if campaign.category_of(name) is None:
        raise ImageError(f"„{name}” nie ma w słowniku ani postaciach graczy kampanii {campaign.key}.")
    campaign = ensure_style(llm, campaign)
    _save_hints(campaign.key, name, hints)
    prompt = image_prompt(llm, campaign, name, hints)
    print(f"[{images.name}] Rysowanie: {name}...")
    data = images.generate(prompt)
    directory = candidates_dir(campaign.key)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"{image_stem(name)}__{stamp}.jpg"
    path.write_bytes(data)
    path.with_suffix(".txt").write_text(prompt, encoding="utf-8")
    return str(path)
