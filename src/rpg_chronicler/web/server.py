"""Lokalny serwer HTTP nowego okna (tylko biblioteka standardowa).

Bezpieczeństwo: nasłuch tylko na 127.0.0.1, losowy port i losowy klucz na każde uruchomienie. Każde zapytanie
/api/ musi mieć klucz w nagłówku X-Token (albo ?t= dla plików audio) i nagłówek Host = 127.0.0.1:port - inaczej
strona z internetu otwarta w przeglądarce mogłaby wołać API przez localhost (CSRF, DNS rebinding).
"""
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import IS_WINDOWS
from ..recording import RecordingError
from ..storage.campaign_sync import SyncError
from ..session import SessionNotFound
from . import api, campaign_api, environment, prompts_api, record_api, recording_api, session_api, sync_api
from .tasks import TaskRunner

STATIC_DIR = Path(__file__).with_name("static")
BODY_LIMIT = 32 * 1024 * 1024  # bajtów zapytania (zdjęcie hasła w base64)


def open_with_system(path: str) -> None:
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 - plik z folderów danych (api.openable)
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App:
    """Stan serwera: klucz, zadania i ostatni sygnał życia okna (do zamykania serwera w trybie przeglądarki)."""

    def __init__(self, runner: TaskRunner | None = None):
        self.token = secrets.token_urlsafe(24)
        self.runner = runner or TaskRunner()
        self.last_seen = time.monotonic()

    # metoda, ścieżka -> funkcja(zapytanie: dict, ciało: dict) -> dane JSON
    def routes(self) -> dict:
        r = self.runner
        return {
            ("GET", "/api/state"): lambda q, b: {**api.state(), "task": r.snapshot(10 ** 12)},
            ("GET", "/api/session"): lambda q, b: api.session_detail(q["name"]),
            ("GET", "/api/transcript"): lambda q, b: api.transcript(q["name"]),
            ("GET", "/api/settings"): lambda q, b: api.settings_payload(),
            ("POST", "/api/settings"): lambda q, b: api.save_setting(b["key"], b["value"]),
            ("POST", "/api/key"): lambda q, b: api.save_key(b["name"], b.get("value", "")),
            ("GET", "/api/changelog"): lambda q, b: api.changelog_html(),
            ("GET", "/api/task"): lambda q, b: r.snapshot(int(q.get("since", 0))),
            ("POST", "/api/task"): lambda q, b: {"error": r.start(b["title"], [str(a) for a in b["args"]])},
            ("POST", "/api/task/cancel"): lambda q, b: r.cancel() or {"ok": True},
            ("POST", "/api/open"): lambda q, b: self._open(b["path"]),
            ("POST", "/api/open-session-file"): lambda q, b: self._open_session_file(b["name"], b["kind"]),
            # etap 2: praca z sesją
            ("GET", "/api/speakers"): lambda q, b: session_api.speakers(q["name"]),
            ("POST", "/api/speakers"): lambda q, b: session_api.save_speakers(b["name"], b["mapping"]),
            ("GET", "/api/discord"): lambda q, b: session_api.discord_info(q["name"]),
            ("POST", "/api/discord/webhook"): lambda q, b: session_api.save_webhook(b["campaign"], b["url"]),
            ("POST", "/api/discord/teaser"): lambda q, b: session_api.save_teaser(b["name"], b.get("text", "")),
            ("POST", "/api/discord/sent"): lambda q, b: session_api.set_sent(b["name"], bool(b["sent"])),
            ("GET", "/api/notes"): lambda q, b: session_api.notes_form(q.get("name") or None, q.get("campaign")),
            ("GET", "/api/notes/name"): lambda q, b: session_api.notes_name(q.get("campaign", ""), q.get("date", "")),
            ("POST", "/api/notes"): lambda q, b: session_api.save_notes(
                b.get("name") or None, b.get("campaign", ""), b.get("date", ""), b.get("text", ""),
                [str(x) for x in b.get("present", [])]),
            ("GET", "/api/delete"): lambda q, b: session_api.delete_plan(q["name"], q["scope"]),
            ("GET", "/api/delete/options"): lambda q, b: session_api.delete_options(q["name"]),
            ("GET", "/api/search"): lambda q, b: session_api.run_search(
                q.get("q", ""), q.get("campaign"), q.get("chronicles", "1") == "1", q.get("transcripts", "1") == "1"),
            # etap 3: kampanie
            ("GET", "/api/campaigns"): lambda q, b: campaign_api.campaign_list(),
            ("POST", "/api/campaigns"): lambda q, b: campaign_api.create(b["key"]),
            ("GET", "/api/campaign"): lambda q, b: campaign_api.detail(q["key"]),
            ("POST", "/api/campaign"): lambda q, b: campaign_api.change(b["key"], b["what"], b),
            ("POST", "/api/campaign/proposals"): lambda q, b: campaign_api.resolve_proposals(
                b["key"], b["shown"], b["accepted"]),
            ("POST", "/api/campaign/memory"): lambda q, b: campaign_api.memory_action(
                b["key"], b["action"], str(b.get("text", "")), b.get("session")),
            ("POST", "/api/campaign/forget"): lambda q, b: campaign_api.forget_answer(
                b["key"], b["question"], b["asked"]),
            ("POST", "/api/campaign/remove-webhook"): lambda q, b: campaign_api.remove_webhook(b["key"]),
            ("GET", "/api/entry"): lambda q, b: campaign_api.entry(q["key"], q["name"]),
            ("POST", "/api/entry/upload"): lambda q, b: campaign_api.upload_image(
                b["key"], b["name"], b["filename"], b["data"]),
            ("POST", "/api/entry/image"): lambda q, b: campaign_api.image_action(b["key"], b["name"], b["action"]),
            # etap 4: nagranie, jakość, statystyki, uzupełnianie
            ("GET", "/api/recording"): lambda q, b: recording_api.recording(q["name"]),
            ("GET", "/api/recording/plan"): lambda q, b: recording_api.trim_plan(
                q["name"], q.get("start", ""), q.get("end", ""), float(q.get("gaps") or 0)),
            ("GET", "/api/stats"): lambda q, b: recording_api.session_stats(q["name"], q.get("campaign") == "1"),
            ("GET", "/api/backfill"): lambda q, b: recording_api.backfill_plan(),
            ("GET", "/api/rec/devices"): lambda q, b: record_api.devices(),
            ("GET", "/api/rec/name"): lambda q, b: record_api.suggest_name(q.get("campaign", ""), q.get("date", "")),
            ("GET", "/api/rec/status"): lambda q, b: record_api.status(),
            ("POST", "/api/rec/preview"): lambda q, b: record_api.preview(b["device"]),
            ("POST", "/api/rec/start"): lambda q, b: record_api.start(b["name"], b["device"], bool(b.get("upload"))),
            ("POST", "/api/rec/stop"): lambda q, b: record_api.stop(),
            ("GET", "/api/rec/finish-args"): lambda q, b: {"args": record_api.finish_args(q["name"])},
            ("GET", "/api/sync"): lambda q, b: sync_api.status(),
            ("POST", "/api/sync"): lambda q, b: sync_api.start(),
            ("GET", "/api/sync/conflict"): lambda q, b: sync_api.conflict(q["path"]),
            ("POST", "/api/sync/resolve"): lambda q, b: sync_api.resolve(b["path"], b["keep"]),
            ("GET", "/api/environment"): lambda q, b: {"done": environment.done(), "status": environment.status()},
            ("GET", "/api/prompts"): lambda q, b: prompts_api.prompt_list(),
            ("GET", "/api/prompt"): lambda q, b: prompts_api.prompt(q["name"]),
            ("POST", "/api/prompt"): lambda q, b: prompts_api.save(b["name"], b["text"]),
            ("POST", "/api/prompt/reset"): lambda q, b: prompts_api.reset(b["name"]),
        }

    def _open(self, path: str) -> dict:
        if not api.openable(path):
            raise ValueError("Tego pliku nie można otworzyć z okna programu")
        open_with_system(path)
        return {"ok": True}

    def _open_session_file(self, name: str, kind: str) -> dict:
        from .. import chronicle
        session = api.find_session(name)
        paths = {"pdf": chronicle.pdf_path(session), "kronika": session.summary_path}
        return self._open(paths[kind])


def make_handler(app: App, port_holder: list):
    routes = app.routes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "rpg-chronicler"

        def log_message(self, *args):  # bez logu każdego zapytania w konsoli
            pass

        # --- odpowiedzi ---

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status)

        # --- sprawdzenia ---

        def _host_ok(self) -> bool:
            return self.headers.get("Host") in {f"127.0.0.1:{port_holder[0]}", f"localhost:{port_holder[0]}"}

        def _token_ok(self, query: dict) -> bool:
            given = self.headers.get("X-Token") or query.get("t", "")
            return secrets.compare_digest(given, app.token)

        # --- obsługa ---

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str) -> None:
            if not self._host_ok():
                return self._error(HTTPStatus.FORBIDDEN, "Zły nagłówek Host")
            url = urlparse(self.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            if not url.path.startswith("/api/"):
                return self._static(url.path) if method == "GET" else self._error(HTTPStatus.NOT_FOUND, "Brak")
            if not self._token_ok(query):
                return self._error(HTTPStatus.FORBIDDEN, "Brak klucza okna")
            app.last_seen = time.monotonic()
            if method == "GET" and url.path == "/api/audio":
                return self._audio(query)
            if method == "GET" and url.path == "/api/image":
                return self._image(query)
            route = routes.get((method, url.path))
            if route is None:
                return self._error(HTTPStatus.NOT_FOUND, f"Nieznane zapytanie {url.path}")
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > BODY_LIMIT:
                    self.close_connection = True
                    return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Za duży plik")
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._error(HTTPStatus.BAD_REQUEST, "Niepoprawny JSON")
            try:
                self._json(route(query, body))
            except (KeyError, ValueError, SessionNotFound, RecordingError, SyncError) as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e.args[0]) if e.args else str(e))
            except Exception as e:  # błąd programu - komunikat do okna, szczegóły w konsoli
                import traceback
                traceback.print_exc()
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")

        def _image(self, query: dict) -> None:
            """Zdjęcie hasła albo propozycja od AI (klucz w ?t=, bo <img> nie wysyła nagłówków)."""
            try:
                path = campaign_api.image_file(query["key"], query["name"], query.get("proposal") == "1")
                data = Path(path).read_bytes()
            except (KeyError, ValueError, OSError):
                return self._error(HTTPStatus.NOT_FOUND, "Brak zdjęcia")
            self._send(HTTPStatus.OK, data, mimetypes.guess_type(path)[0] or "application/octet-stream")

        def _audio(self, query: dict) -> None:
            """Nagranie sesji z obsługą zakresów (Range) - odtwarzacz pobiera tylko potrzebny fragment."""
            try:
                path = session_api.audio_path(query["name"])
            except (KeyError, ValueError, SessionNotFound) as e:
                return self._error(HTTPStatus.NOT_FOUND, str(e))
            size = os.path.getsize(path)
            start, end, status = 0, size - 1, HTTPStatus.OK
            header = self.headers.get("Range", "")
            if header.startswith("bytes="):
                first, _, last = header[6:].split(",")[0].partition("-")
                try:
                    if first:
                        start, end = int(first), min(int(last) if last else size - 1, size - 1)
                    else:  # ostatnie N bajtów
                        start = max(0, size - int(last))
                except ValueError:
                    start, end = 0, size - 1
                if start > end or start >= size:
                    return self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", "text/plain",
                                      {"Content-Range": f"bytes */{size}"})
                status = HTTPStatus.PARTIAL_CONTENT
            length = end - start + 1
            content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.lower().endswith(".m4a"):
                content_type = "audio/mp4"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")  # po przycięciu pod tym samym adresem jest inne nagranie
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # odtwarzacz przerwał pobieranie (przewinięcie, stop)

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "/index.html") else path.removeprefix("/static/")
            target = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "Brak pliku")
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type.endswith("javascript"):
                content_type += "; charset=utf-8"
            extra = {"Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                                "style-src 'self' 'unsafe-inline'")}
            self._send(HTTPStatus.OK, target.read_bytes(), content_type, extra)

    return Handler


def start_server(app: App, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Uruchamia serwer w wątku; zwraca (serwer, adres strony z kluczem)."""
    port_holder = [port]
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port_holder))
    server.daemon_threads = True
    port_holder[0] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port_holder[0]}/#t={app.token}"


if __name__ == "__main__":  # serwer bez okna (do prób): python -m rpg_chronicler.web.server
    _server, _url = start_server(App())
    print(_url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sys.exit(0)
