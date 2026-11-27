"""Nagrywanie sesji w oknie: mikrofony, podgląd głośności, start/stop. Obróbkę po nagraniu robi zadanie CLI
`record SESJA --dokoncz` (pasek zadań, postęp), więc okno zostaje responsywne."""
import datetime

from .. import notes, recording, settings
from ..campaigns import campaign_key, load_campaigns
from ..session import list_sessions

recorder = recording.Recorder()


def _saved(key: str, default):
    return settings.load().get(key, default)   # z pliku, bo okno może zmienić je w trakcie pracy


def devices() -> dict:
    found = recording.list_devices()
    chosen = _saved("nagrywanie.mikrofon", "")
    if chosen not in {d.id for d in found}:
        chosen = found[0].id if found else ""
    campaigns = sorted(set(load_campaigns()) | {k for s in list_sessions() if (k := campaign_key(s.name))},
                       key=str.casefold)
    return {"devices": [{"id": d.id, "label": d.label} for d in found], "device": chosen, "campaigns": campaigns,
            "upload": bool(_saved("nagrywanie.wyslij_na_drive", False))}


def suggest_name(campaign: str, date: str) -> dict:
    try:
        name = notes.session_name(campaign, datetime.date.fromisoformat(date))
    except (ValueError, notes.NotesError) as e:
        return {"name": "", "error": str(e) if campaign.strip() else ""}
    try:
        recording.check_name(name)
    except recording.RecordingError as e:
        return {"name": name, "error": str(e)}
    return {"name": name, "error": ""}


def preview(device: str) -> dict:
    recorder.preview(device)
    return status()


def start(name: str, device: str, upload: bool) -> dict:
    recorder.start(name.strip(), device)
    settings.update({"nagrywanie.mikrofon": device, "nagrywanie.wyslij_na_drive": bool(upload)})
    return status()


def stop() -> dict:
    """Zatrzymuje nagrywanie albo podgląd; okno uruchamia potem obróbkę (`finish_args`)."""
    name = recorder.stop()
    return {**status(), "stopped": name}


def finish_args(name: str) -> list[str]:
    upload = bool(_saved("nagrywanie.wyslij_na_drive", False))
    return ["record", name, "--dokoncz", "--wyslij" if upload else "--nie-wysylaj"]


def status() -> dict:
    data = recorder.status()
    if data["name"] is None and data["recording"] is False and recorder.name and not recorder.active:
        data["interrupted"] = recorder.name   # ffmpeg zakończył się sam (np. odłączony mikrofon)
    return data


def shutdown() -> None:
    """Zamknięcie okna: ffmpeg kończy plik porządnie; nagranie czeka na „Dokończ” przy następnym starcie."""
    recorder.stop()
