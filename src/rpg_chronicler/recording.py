"""Nagrywanie sesji z mikrofonu przez ffmpeg (Linux: PipeWire/PulseAudio, Windows: DirectShow).

Surowy dźwięk idzie do `AUDIO_DIR/oryginaly/.<sesja>.nagrywanie.mka` (FLAC w Matroska - plik da się odczytać
nawet po zaniku prądu, w przeciwieństwie do WAV/FLAC z nagłówkiem zapisywanym na końcu). Po zatrzymaniu
`finish` przepuszcza go przez filtr użytkownika (domyślnie highpass + kompresor), zapisuje jako
`AUDIO_DIR/<sesja>.flac` (mono) i przenosi surowy plik do `oryginaly/<sesja>.mka`. Ukryty plik bez działającego
nagrywania = nagranie przerwane (awaria, zamknięty program) - `unfinished()` i „Dokończ nagranie”.
Tylko stdlib + ffmpeg.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import progress
from . import session as _session
from .config import IS_WINDOWS, RECORDING_FILTER_DEFAULT

ORIGINALS_DIR = "oryginaly"
RAW_SUFFIX = ".nagrywanie.mka"
FINAL_EXT = ".flac"
DEFAULT_FILTER = RECORDING_FILTER_DEFAULT
LEVEL_KEY = "lavfi.astats.Overall.Peak_level"
# szczyt sygnału co 0,1 s (przy 48 kHz) na stdout - wskaźnik głośności
LEVEL_FILTER = f"asetnsamples=n=4800,astats=metadata=1:reset=1,ametadata=mode=print:key={LEVEL_KEY}:file=-:direct=1"
SILENT_DB = -90.0
NAME_RE = re.compile(r"^[^\\/:*?\"<>|\s.][^\\/:*?\"<>|\s]*$")
BYTES_PER_SECOND = 48000 * 2 * 2 * 0.6   # FLAC stereo 48 kHz ≈ 60% PCM - do szacowania miejsca na dysku


class RecordingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    id: str      # to, co dostaje ffmpeg (-i)
    label: str   # opis dla użytkownika


# --- mikrofony ---

def parse_pactl(text: str) -> list[Device]:
    """Wejścia z `pactl -f json list sources` bez „monitorów” (dźwięk wychodzący z głośników)."""
    devices = []
    for source in json.loads(text or "[]"):
        name = source.get("name", "")
        if not name or name.endswith(".monitor") or source.get("monitor_source") == name:
            continue
        spec = source.get("sample_specification", "")
        devices.append(Device(name, f"{source.get('description') or name}" + (f" ({spec})" if spec else "")))
    return devices


def parse_dshow(text: str) -> list[Device]:
    """Mikrofony z `ffmpeg -list_devices true -f dshow -i dummy` (Windows)."""
    devices = []
    for line in text.splitlines():
        match = re.search(r'\]\s+"(.+)"\s+\(audio\)', line)
        if match:
            devices.append(Device(f"audio={match[1]}", match[1]))
    return devices


def list_devices() -> list[Device]:
    if IS_WINDOWS:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW)
        return parse_dshow(proc.stderr)
    if not shutil.which("pactl"):
        return [Device("default", "Domyślny mikrofon systemu")]
    proc = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    try:
        devices = parse_pactl(proc.stdout) if proc.returncode == 0 else []
    except ValueError:
        devices = []
    return devices or [Device("default", "Domyślny mikrofon systemu")]


def input_args(device: str) -> list[str]:
    return ["-f", "dshow", "-i", device] if IS_WINDOWS else ["-f", "pulse", "-i", device]


# --- pliki ---

def originals_dir() -> Path:
    return Path(_session.AUDIO_DIR) / ORIGINALS_DIR


def raw_path(name: str) -> Path:
    return originals_dir() / f".{name}{RAW_SUFFIX}"


def kept_raw_path(name: str) -> Path:
    return originals_dir() / f"{name}.mka"


def final_path(name: str) -> Path:
    return Path(_session.AUDIO_DIR) / f"{name}{FINAL_EXT}"


def check_name(name: str) -> None:
    if not NAME_RE.match(name or ""):
        raise RecordingError(f"Nazwa sesji „{name}” nie może być pusta ani zawierać spacji, „/” i podobnych znaków.")
    if name in {s.name for s in _session.list_sessions()} or raw_path(name).exists() or kept_raw_path(name).exists():
        raise RecordingError(f"Sesja {name} już istnieje - wybierz inną datę albo nazwę.")


def unfinished(active: str | None = None) -> list[str]:
    """Nagrania przerwane (surowy plik bez obróbki), poza tym, które właśnie trwa."""
    folder = originals_dir()
    if not folder.is_dir():
        return []
    names = [p.name[1:-len(RAW_SUFFIX)] for p in folder.iterdir() if p.name.startswith(".") and p.name.endswith(RAW_SUFFIX)]
    return sorted(n for n in names if n != active)


def free_bytes() -> int:
    folder = Path(_session.AUDIO_DIR)
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return shutil.disk_usage(folder).free


# --- usypianie ---

_inhibit_what: str | None = None


def inhibit_prefix() -> list[str]:
    """Linux: systemd-inhibit blokuje uśpienie (także zamknięciem klapy laptopa), dopóki działa ffmpeg."""
    global _inhibit_what
    if IS_WINDOWS or not shutil.which("systemd-inhibit"):
        return []
    if _inhibit_what is None:
        _inhibit_what = ""
        for what in ("sleep:idle:handle-lid-switch", "sleep:idle", "sleep"):
            probe = ["systemd-inhibit", f"--what={what}", "--who=RPG Chronicler", "--why=test", "true"]
            if subprocess.run(probe, capture_output=True).returncode == 0:
                _inhibit_what = what
                break
    if not _inhibit_what:
        return []
    return ["systemd-inhibit", f"--what={_inhibit_what}", "--who=RPG Chronicler", "--why=Nagrywanie sesji RPG",
            "--mode=block"]


def _windows_keep_awake(on: bool) -> None:
    if IS_WINDOWS:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


# --- nagrywanie ---

def capture_command(source: list[str], raw: Path | None) -> list[str]:
    """ffmpeg: surowy dźwięk do pliku (albo bez pliku - sam podgląd głośności) i szczyt sygnału na stdout."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", *source]
    if raw is not None:
        # małe klastry Matroska: na dysku najwyżej ok. 2 s dźwięku bez zapisu (awaria = utrata końcówki)
        command += ["-map", "0:a", "-c:a", "flac", "-cluster_time_limit", "2000", "-flush_packets", "1",
                    "-y", str(raw)]
    command += ["-map", "0:a", "-af", LEVEL_FILTER, "-f", "null", "-"]
    return command


class Recorder:
    """Jedno nagrywanie (albo podgląd głośności) naraz; ffmpeg w podprocesie, poziom czytany w wątku."""

    def __init__(self, source_args=input_args):
        self.source_args = source_args
        self.process: subprocess.Popen | None = None
        self.name: str | None = None     # None przy samym podglądzie
        self.device = ""
        self.started = 0.0
        self.level = SILENT_DB
        self.level_time = 0.0
        self.error = ""
        self._spawns = 0
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def recording(self) -> bool:
        return self.active and self.name is not None

    def _spawn(self, device: str, raw: Path | None) -> None:
        command = capture_command(self.source_args(device), raw)
        if raw is not None:
            command = inhibit_prefix() + command
        self.error = ""
        self.level, self.level_time = SILENT_DB, 0.0
        self._spawns += 1
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace",
                                        creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
        self.device, self.started = device, time.monotonic()
        threading.Thread(target=self._read_levels, args=(self.process, raw is not None), daemon=True).start()
        threading.Thread(target=self._read_errors, args=(self.process, self._spawns), daemon=True).start()

    def _read_levels(self, process: subprocess.Popen, keep_awake: bool) -> None:
        if keep_awake:
            _windows_keep_awake(True)
        try:
            for line in process.stdout:
                if line.startswith(LEVEL_KEY + "="):
                    try:
                        value = float(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    self.level = max(SILENT_DB, value) if value == value else SILENT_DB  # nan przy ciszy
                    self.level_time = time.monotonic()
        finally:
            if keep_awake:
                _windows_keep_awake(False)

    def _read_errors(self, process: subprocess.Popen, spawn: int) -> None:
        lines = [line.strip() for line in process.stderr if line.strip()]
        if lines and spawn == self._spawns:   # nie nadpisuje błędu nowszego ffmpeg
            self.error = lines[-1]

    def preview(self, device: str) -> None:
        """Podgląd głośności wybranego mikrofonu bez zapisu."""
        with self._lock:
            if self.recording:
                raise RecordingError("Trwa nagrywanie - najpierw je zatrzymaj.")
            self._stop_process()
            self.name = None
            self._spawn(device, None)

    def start(self, name: str, device: str) -> Path:
        with self._lock:
            if self.recording:
                raise RecordingError(f"Trwa już nagrywanie {self.name}.")
            check_name(name)
            self._stop_process()
            raw = raw_path(name)
            raw.parent.mkdir(parents=True, exist_ok=True)
            self.name = name
            self._spawn(device, raw)
            return raw

    def _stop_process(self, timeout: float = 15) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.stdin.write("q\n")   # ffmpeg kończy plik porządnie
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.process = None

    def stop(self) -> str | None:
        """Kończy nagrywanie (albo podgląd); zwraca nazwę nagranej sesji."""
        with self._lock:
            name = self.name if self.process is not None else None
            self._stop_process()
            self.name = None
            return name

    def status(self) -> dict:
        alive = self.active
        if not alive and self.name is not None and self.process is not None:
            # ffmpeg sam się zakończył (odłączony mikrofon, błąd urządzenia) - nagranie zostaje do dokończenia
            self.process = None
        elapsed = time.monotonic() - self.started if alive else 0.0
        fresh = alive and time.monotonic() - self.level_time < 1.5
        raw = raw_path(self.name) if self.name else None
        size = raw.stat().st_size if raw is not None and raw.exists() else 0
        free = free_bytes()
        return {"recording": alive and self.name is not None, "preview": alive and self.name is None,
                "name": self.name if alive else None, "device": self.device if alive else "",
                "elapsed": round(elapsed, 1), "level": round(self.level, 1) if fresh else SILENT_DB,
                "size": size, "free": free, "free_hours": round(free / BYTES_PER_SECOND / 3600, 1),
                "error": self.error if not alive else "", "unfinished": unfinished(self.name if alive else None)}


# --- po nagraniu ---

def duration(path: Path) -> float | None:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def finish(name: str, audio_filter: str = DEFAULT_FILTER) -> Path:
    """Surowe nagranie → filtr użytkownika, mono FLAC w folderze nagrań; surowy plik do oryginaly/<sesja>.mka."""
    raw = raw_path(name)
    if not raw.exists():
        raise RecordingError(f"Nie ma surowego nagrania {name} ({raw}).")
    target = final_path(name)
    if target.exists():
        raise RecordingError(f"Nagranie {target} już istnieje.")
    total = duration(raw)
    tmp = target.with_name(f".{name}.obrobka{FINAL_EXT}")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(raw)]
    if audio_filter.strip():
        command += ["-af", audio_filter]
    command += ["-ac", "1", "-c:a", "flac", "-progress", "pipe:1", "-nostats", str(tmp)]
    progress.report("obróbka nagrania", name, 0, round(total) if total else None)
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True)
    reader.start()
    for line in proc.stdout:
        if line.startswith("out_time_us=") and total:
            try:
                done = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                continue
            progress.report("obróbka nagrania", name, min(round(done), round(total)), round(total))
    proc.wait()
    reader.join(5)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        details = "".join(errors).strip().splitlines()
        raise RecordingError(f"ffmpeg nie przetworzył nagrania {name}: {details[-1] if details else proc.returncode}")
    os.replace(tmp, target)
    _move_when_free(raw, kept_raw_path(name))
    return target


def _move_when_free(source: Path, target: Path, seconds: float = 10) -> None:
    """Windows nie przeniesie pliku, który ktoś trzyma otwarty (np. kończący się ffmpeg) - chwilę ponawiamy."""
    end = time.monotonic() + seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() > end:
                raise RecordingError(f"Surowe nagranie {source} jest wciąż otwarte przez inny program (czy nagrywanie "
                                     "nie trwa w innym oknie?). Gotowy plik jest już w folderze nagrań.") from None
            time.sleep(0.5)


def record_in_terminal(name: str, device: str) -> None:
    """CLI: nagrywa do Enter / Ctrl+C."""
    recorder = Recorder()
    raw = recorder.start(name, device)
    print(f"[INFO] Nagrywanie {name} z: {device}\n[INFO] Surowy plik: {raw}\nEnter albo Ctrl+C kończy nagrywanie.")
    try:
        if sys.stdin.isatty():
            input()
        else:
            while recorder.active:
                time.sleep(1)
    except (KeyboardInterrupt, EOFError):
        pass
    elapsed = time.monotonic() - recorder.started
    recorder.stop()
    if recorder.error:
        print(f"[OSTRZEŻENIE] ffmpeg: {recorder.error}")
    print(f"[SUKCES] Nagrano {name} ({time.strftime('%H:%M:%S', time.gmtime(elapsed))}).")
