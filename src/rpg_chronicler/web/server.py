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
from ..session import SessionNotFound
from . import api
from .tasks import TaskRunner

STATIC_DIR = Path(__file__).with_name("static")


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
            route = routes.get((method, url.path))
            if route is None:
                return self._error(HTTPStatus.NOT_FOUND, f"Nieznane zapytanie {url.path}")
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._error(HTTPStatus.BAD_REQUEST, "Niepoprawny JSON")
            try:
                self._json(route(query, body))
            except (KeyError, ValueError, SessionNotFound) as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e.args[0]) if e.args else str(e))
            except Exception as e:  # błąd programu - komunikat do okna, szczegóły w konsoli
                import traceback
                traceback.print_exc()
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")

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
