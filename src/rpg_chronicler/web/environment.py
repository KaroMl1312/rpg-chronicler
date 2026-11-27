"""Sprawdzenie w tle, czy .venv ma biblioteki transkrypcji (po aktualizacji systemu albo przerwanej instalacji
potrafi być zepsute, choć samo okno działa). Wynik pokazuje baner w oknie. Pełna diagnoza: ./sprawdz-srodowisko."""
import subprocess
import sys
import threading

from ..config import DIARIZATION_ENGINE, IS_WINDOWS, PROJECT_ROOT, REPAIR_HINT

MODULES = ["faster_whisper", "pyannote.audio", "torchcodec.decoders"]
_result: dict = {"error": None, "done": False}


def modules() -> list[str]:
    return MODULES + (["onnxruntime"] if DIARIZATION_ENGINE == "onnx" else [])


def check() -> str | None:
    """Błąd importu bibliotek w osobnym procesie (None = działa)."""
    try:
        proc = subprocess.run([sys.executable, "-c", "import " + ", ".join(modules())], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=600, cwd=str(PROJECT_ROOT),
                              creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if proc.returncode == 0:
        return None
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    return lines[-1] if lines else "nieznany błąd"


def start() -> None:
    def run() -> None:
        _result["error"] = check()
        _result["done"] = True
    threading.Thread(target=run, daemon=True).start()


def done() -> bool:
    return _result["done"]


def status() -> dict | None:
    if not _result["error"]:
        return None
    return {"error": _result["error"], "hint": REPAIR_HINT, "folder": str(PROJECT_ROOT)}
