"""python -m rpg_chronicler.web [--przegladarka] - nowe okno programu.

Okno wybierane po kolei: pywebview (Windows: wbudowany Edge WebView2), na Linuksie GTK 4 + WebKit z systemowego
Pythona (web/okno_gtk.py), a w ostateczności przeglądarka. W trybie przeglądarki serwer kończy pracę, gdy okno
przestanie się odzywać (zamknięta karta).
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ..config import IS_WINDOWS
from .server import App, start_server

SYSTEM_PYTHON = "/usr/bin/python3"
GTK_SHELL = Path(__file__).with_name("okno_gtk.py")
BROWSER_TIMEOUT = 30  # sekund bez sygnału z karty przeglądarki = okno zamknięte


def _webview(url: str) -> bool:
    try:
        import webview
    except ImportError:
        return False
    window = webview.create_window("RPG Chronicles", url, width=1280, height=820, min_size=(900, 600), maximized=True)
    window.events.closing += closing_handler(window)
    webview.start()
    return True


def closing_handler(window):
    """Zamykanie okna pywebview: strona zapisuje zmiany i pyta o trwające zadanie (confirmClose w app.js).

    Zdarzenie przychodzi w wątku okna, więc JavaScript wołamy z osobnego wątku (inaczej zakleszczenie), a samo
    zamknięcie odwołujemy (False) do czasu odpowiedzi.
    """
    state = {"asking": False, "done": False}

    def answered(close) -> None:
        state["asking"] = False
        if close is not False:
            state["done"] = True
            window.destroy()

    def ask() -> None:
        try:
            window.evaluate_js("confirmClose()", answered)
        except Exception:  # strona nie działa - nie blokujemy zamknięcia
            answered(True)

    def on_closing():
        if state["done"]:
            return None
        if not state["asking"]:
            state["asking"] = True
            threading.Thread(target=ask, daemon=True).start()
        return False

    return on_closing


def _gtk_shell(url: str) -> bool:
    if IS_WINDOWS or not Path(SYSTEM_PYTHON).exists():
        return False
    check = ("import gi; gi.require_version('Gtk', '4.0'); gi.require_version('WebKit', '6.0'); "
             "from gi.repository import WebKit")
    if subprocess.run([SYSTEM_PYTHON, "-c", check], capture_output=True).returncode != 0:
        return False
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.run([SYSTEM_PYTHON, str(GTK_SHELL), url], env=env)
    return True


def _browser(url: str, app: App) -> None:
    # Edge/Chrome w trybie aplikacji: osobne okno bez pasków przeglądarki
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            break
    else:
        webbrowser.open(url)
    print(f"[INFO] Okno otwarte w przeglądarce: {url}\n[INFO] Zamknij kartę, żeby zakończyć (albo Ctrl+C).")
    app.last_seen = time.monotonic()
    try:
        while time.monotonic() - app.last_seen < BROWSER_TIMEOUT or app.runner.running:
            time.sleep(2)
    except KeyboardInterrupt:
        pass


def main(argv: list[str]) -> int:
    app = App()
    server, url = start_server(app)
    try:
        if "--przegladarka" in argv or not (_webview(url) or _gtk_shell(url)):
            _browser(url, app)
    finally:
        if app.runner.running:  # zamknięte okno nie zostawia osieroconego zadania
            app.runner.cancel()
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
