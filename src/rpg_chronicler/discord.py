"""Wysyłka wiadomości na kanał Discorda przez webhook (tylko biblioteka standardowa).

Webhook tworzy się w ustawieniach kanału Discorda: Integracje → Webhooki → Nowy webhook → Kopiuj URL.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

WEBHOOK_RE = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
USER_AGENT = "DiscordBot (rpg-chronicler, 0.1)"  # Discord odrzuca domyślny agent urllib
EMBED_COLOR = 0x8B4513   # brąz pergaminu
DESCRIPTION_LIMIT = 4000  # Discord: opis osadzenia do 4096 znaków
TITLE_LIMIT = 256
MAX_FILE_BYTES = 10 * 1024 * 1024
TIMEOUT = 60


class DiscordError(Exception):
    pass


def is_valid_webhook(url: str) -> bool:
    return bool(WEBHOOK_RE.match(url.strip()))


def build_message(title: str, teaser: str, footer: str, filename: str | None) -> dict:
    embed = {"title": title[:TITLE_LIMIT], "description": teaser[:DESCRIPTION_LIMIT], "color": EMBED_COLOR,
             "footer": {"text": footer[:2000]}}
    payload = {"username": "Kronikarz", "embeds": [embed], "allowed_mentions": {"parse": []}}
    if filename:
        payload["attachments"] = [{"id": 0, "filename": filename}]
    return payload


def _multipart(payload: dict, file_path: str | None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
              f"Content-Type: application/json\r\n\r\n").encode() + json.dumps(payload, ensure_ascii=False).encode()]
    if file_path:
        name = os.path.basename(file_path).replace('"', "")
        with open(file_path, "rb") as f:
            content = f.read()
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'
                      "Content-Type: application/pdf\r\n\r\n").encode() + content)
    body = b"\r\n".join(parts) + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def send(webhook_url: str, payload: dict, file_path: str | None = None, attempts: int = 3) -> str | None:
    """Wysyła wiadomość (z opcjonalnym załącznikiem); zwraca id wiadomości. Rzuca DiscordError."""
    if not is_valid_webhook(webhook_url):
        raise DiscordError("Niepoprawny adres webhooka (oczekiwany: https://discord.com/api/webhooks/…).")
    if file_path and os.path.getsize(file_path) > MAX_FILE_BYTES:
        raise DiscordError("Załącznik jest większy niż 10 MB - Discord go nie przyjmie.")
    body, content_type = _multipart(payload, file_path)
    url = webhook_url.strip() + "?wait=true"
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": content_type, "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read() or b"{}").get("id")
        except urllib.error.HTTPError as e:
            details = _error_details(e)
            if e.code == 429 and attempt < attempts:
                time.sleep(min(30.0, float(e.headers.get("Retry-After", 2))))
                continue
            if e.code in (401, 403, 404):
                raise DiscordError("Discord nie przyjął webhooka (usunięty albo błędny adres) - "
                                   f"skopiuj go ponownie z ustawień kanału. {details}") from e
            if e.code >= 500 and attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise DiscordError(f"Discord zwrócił błąd {e.code}: {details}") from e
        except urllib.error.URLError as e:
            if attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise DiscordError(f"Brak połączenia z Discordem: {e.reason}") from e
    raise DiscordError("Nie udało się wysłać wiadomości.")


def _error_details(error: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(error.read() or b"{}")
        return str(data.get("message", ""))[:300]
    except (ValueError, OSError):
        return ""
