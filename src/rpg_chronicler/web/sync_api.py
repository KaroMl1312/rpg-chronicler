"""Synchronizacja danych kampanii w oknie: w tle (przy starcie i z menu), konflikty do rozstrzygnięcia."""
import base64
import datetime
import threading

from .. import settings
from ..config import RCLONE_TXT_REMOTE
from ..storage import campaign_sync

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
PREVIEW_LIMIT = 3 * 1024 * 1024    # większe obrazki bez podglądu

_state = {"running": False, "seq": 0, "result": None, "error": "", "finished": ""}
_lock = threading.RLock()   # start() woła status() pod blokadą


def _remote() -> str:
    return settings.load().get("google_drive.transkrypcje", RCLONE_TXT_REMOTE)


def engine() -> campaign_sync.CampaignSync:
    return campaign_sync.CampaignSync(remote_name=_remote())


def auto_enabled() -> bool:
    return bool(settings.load().get("google_drive.synchronizuj_kampanie", True))


def start() -> dict:
    """Synchronizacja w wątku (okno pyta o wynik przez status())."""
    with _lock:
        if _state["running"]:
            return status()
        if not campaign_sync.remote_configured(_remote()):
            _state.update(error="rclone nie jest skonfigurowany (brak programu albo remote'a Google Drive).")
            return status()
        _state.update(running=True, error="")

    def run() -> None:
        result, error = None, ""
        try:
            result = engine().run().to_dict()
        except campaign_sync.SyncError as e:
            error = str(e)
        except Exception as e:   # nie może wywrócić serwera
            error = f"{type(e).__name__}: {e}"
        with _lock:
            _state.update(running=False, result=result, error=error, seq=_state["seq"] + 1,
                          finished=datetime.datetime.now().isoformat(timespec="seconds"))
    threading.Thread(target=run, daemon=True).start()
    return status()


def start_if_enabled() -> None:
    if auto_enabled():
        start()


def status() -> dict:
    try:
        sync = engine()
        pending, last = sync.pending, sync.last_sync
    except OSError:
        pending, last = [], None
    with _lock:
        return {**_state, "pending": pending, "last_sync": last}


def _preview(path, text: bool) -> dict | None:
    if path is None:
        return None
    stat = path.stat()
    info = {"size": stat.st_size, "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="minutes")}
    if text:
        info["text"] = path.read_text(encoding="utf-8", errors="replace")
    elif path.suffix.lower() in IMAGE_TYPES and stat.st_size <= PREVIEW_LIMIT:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        info["image"] = f"data:{IMAGE_TYPES[path.suffix.lower()]};base64,{data}"
    return info


def conflict(path: str) -> dict:
    details = engine().conflict(path)
    return {"path": path, "found": details["found"], "text": details["text"],
            "local": _preview(details["local"], details["text"]), "remote": _preview(details["remote"], details["text"])}


def resolve(path: str, keep: str) -> dict:
    extra = engine().resolve(path, keep)
    return {**status(), "extra": extra}
