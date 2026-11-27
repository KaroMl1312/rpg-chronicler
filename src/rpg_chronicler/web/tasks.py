"""Zadania w tle dla nowego okna: komenda CLI w osobnym procesie, jej log i postęp (protokół progress.py).

Jedno zadanie naraz, jak w oknie GTK. Okno odpytuje `snapshot(od)` co pół sekundy - dostaje nowe linie logu,
bieżący etap z postępem i informację o zakończeniu. Długie zadania nie blokują serwera (osobny wątek czyta wyjście).
"""
import codecs
import os
import re
import signal
import subprocess
import sys
import threading
import time

from .. import progress
from ..config import IS_WINDOWS, PROJECT_ROOT
from .text import estimate_remaining, new_proposals, proposals_snapshot

CANCEL_TIMEOUT = 10        # sekundy od przerwania do wymuszonego zakończenia
LOG_LIMIT = 5000           # tyle ostatnich linii logu trzyma serwer
LINE_END_RE = re.compile(r"(\r\n|\r|\n)")
# Pierwsze słowo argumentów - nic poza komendami programu okno nie uruchomi
COMMANDS = {"run", "status", "sync", "transcribe", "speakers", "summarize", "add-session", "voices", "brief",
            "quotes", "pdf", "discord", "discord-test", "glossary", "memory", "revise", "encyclopedia", "describe",
            "recap", "ideas", "gm-notes", "ask", "image", "diary", "stats", "silence", "trim", "check", "fix-loops",
            "backfill", "archive", "delete", "migrate", "upload", "record"}


class TaskRunner:
    def __init__(self, command: list[str] | None = None):
        # Serwer działa w .venv, więc CLI to ten sam Python (bez szukania .venv/bin czy .venv\Scripts)
        self.command = command or [sys.executable, "-m", "rpg_chronicler"]
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._lines: list[tuple[int, str]] = []
        self._seq = 0
        self._title = ""
        self._started = 0.0
        self._progress: dict | None = None
        self._status = ""
        self._cancelled = False
        self._finished: dict | None = None
        self._proposals_before: dict = {}

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self, title: str, args: list[str]) -> str | None:
        """Uruchamia `rpg-chronicler <args>`; zwraca opis błędu albo None."""
        if not args or args[0] not in COMMANDS:
            return f"Nieznana komenda: {args[0] if args else '(brak)'}"
        if args[0] == "record" and "--dokoncz" not in args:   # samo nagrywanie okno robi przez record_api
            return "Okno uruchamia tylko obróbkę nagrania (record --dokoncz)."
        with self._lock:
            if self._process is not None:
                return "Inne zadanie jest w toku."
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
            env[progress.ENV_VAR] = "json"
            env.pop("PYTHONPATH", None)
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            try:
                self._process = subprocess.Popen(self.command + args, stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 cwd=str(PROJECT_ROOT), env=env, creationflags=flags)
            except OSError as e:
                return f"Nie udało się uruchomić zadania: {e}"
            self._title, self._started = title, time.monotonic()
            self._progress, self._status, self._cancelled, self._finished = None, "", False, None
            self._proposals_before = proposals_snapshot()
            self._add_line(f"$ rpg-chronicler {' '.join(args)}")
            process = self._process
        threading.Thread(target=self._read, args=(process,), daemon=True).start()
        return None

    def cancel(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            self._cancelled = True
        if IS_WINDOWS:  # Windows nie ma SIGINT dla innego procesu; zapisy plików są atomowe, więc to bezpieczne
            process.terminate()
            return
        process.send_signal(signal.SIGINT)  # CLI kończy się czysto (KeyboardInterrupt)

        def force_exit():
            if self._process is process:
                process.kill()

        threading.Timer(CANCEL_TIMEOUT, force_exit).start()

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            fraction = self._progress.get("fraction") if self._progress else None
            elapsed = time.monotonic() - self._started if self._process else 0
            return {
                "running": self._process is not None,
                "title": self._title if self._process else "",
                "progress": self._progress,
                "status": self._status,
                "elapsed": elapsed,
                "remaining": estimate_remaining(elapsed, fraction) if fraction is not None else None,
                "lines": [text for seq, text in self._lines if seq > since],
                "seq": self._seq,
                "finished": self._finished,
            }

    # --- odczyt wyjścia (osobny wątek) ---

    def _add_line(self, text: str) -> None:
        self._seq += 1
        self._lines.append((self._seq, text))
        if len(self._lines) > LOG_LIMIT:
            del self._lines[:len(self._lines) - LOG_LIMIT]

    def _read(self, process: subprocess.Popen) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        while True:
            data = process.stdout.read1(65536) if hasattr(process.stdout, "read1") else process.stdout.read(4096)
            text = decoder.decode(data, final=not data)
            parts = LINE_END_RE.split(buffer + text)
            with self._lock:
                for line, separator in zip(parts[0:-1:2], parts[1::2]):
                    self._handle_line(line, transient=separator == "\r")
            buffer = parts[-1]
            if not data:
                break
        code = process.wait()
        with self._lock:
            if buffer:
                self._handle_line(buffer, transient=False)
            success = code == 0 and not self._cancelled
            description = "przerwano" if self._cancelled else ("zakończono" if code == 0 else f"błąd (kod {code})")
            self._add_line(f"--- {self._title}: {description} ---")
            messages = [{"campaign": key, "text": text}
                        for key, text in new_proposals(self._proposals_before, proposals_snapshot())]
            self._finished = {"title": self._title, "success": success, "description": description,
                              "seq": self._seq, "proposals": messages}
            self._process = None

    def _handle_line(self, line: str, transient: bool) -> None:
        data = progress.parse(line)
        if data is not None:
            self._progress = {"stage": data.get("etap") or "", "session": data.get("sesja") or "",
                              "fraction": progress.fraction(data)}
        elif transient:
            if line.strip():
                self._status = line.strip()
        else:
            self._add_line(line)
