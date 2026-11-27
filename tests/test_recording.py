"""Nagrywanie sesji: mikrofony, nagrywanie przez ffmpeg (ton testowy zamiast mikrofonu), obróbka, okno."""
import json
import shutil
import subprocess
import time

import pytest

from rpg_chronicler import recording, settings
from rpg_chronicler.web import record_api
from rpg_chronicler.web.tasks import TaskRunner

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="brak ffmpeg")


def tone(device):
    """Ton testowy w czasie rzeczywistym zamiast mikrofonu (cisza dla „cisza”)."""
    source = "anullsrc=r=48000:cl=mono" if device == "cisza" else "sine=f=440:r=48000,volume=0.4"
    return ["-re", "-f", "lavfi", "-i", source]


def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.1)
    return False


def test_microphones_without_monitors():
    text = json.dumps([
        {"name": "alsa_output.usb-X.analog-stereo.monitor", "description": "Monitor of X", "sample_specification": "s16le"},
        {"name": "alsa_input.usb-EMEET.analog-stereo", "description": "EMEET OfficeCore", "sample_specification": "s16le 2ch 48000Hz"},
    ])
    assert recording.parse_pactl(text) == [
        recording.Device("alsa_input.usb-EMEET.analog-stereo", "EMEET OfficeCore (s16le 2ch 48000Hz)")]
    dshow = ('[in#0 @ 0000] "Integrated Camera" (video)\n'
             '[in#0 @ 0000] "Mikrofon (EMEET M0 Plus)" (audio)\n'
             '[in#0 @ 0000]   Alternative name "@device_cm_{33D9A762}\\wave_{1234}"\n')
    assert recording.parse_dshow(dshow) == [recording.Device("audio=Mikrofon (EMEET M0 Plus)", "Mikrofon (EMEET M0 Plus)")]


def test_capture_command_writes_flac_and_levels():
    command = recording.capture_command(["-f", "pulse", "-i", "mic"], recording.Path("/x/.S_261127.nagrywanie.mka"))
    assert command[:3] == ["ffmpeg", "-hide_banner", "-loglevel"] and "flac" in command and "-cluster_time_limit" in command
    assert any("astats" in part and "direct=1" in part for part in command)
    assert "flac" not in recording.capture_command(["-f", "pulse", "-i", "mic"], None)   # podgląd bez zapisu


def test_names(workspace):
    workspace.add_audio("Warhammer_261120")
    for bad in ("", "Warhammer 261127", "../Warhammer_261127", ".ukryta"):
        with pytest.raises(recording.RecordingError):
            recording.check_name(bad)
    with pytest.raises(recording.RecordingError, match="już istnieje"):
        recording.check_name("Warhammer_261120")
    recording.check_name("Warhammer_261127")
    assert record_api.suggest_name("Warhammer", "2026-11-27") == {"name": "Warhammer_261127", "error": ""}
    assert "już istnieje" in record_api.suggest_name("Warhammer", "2026-11-20")["error"]
    assert record_api.suggest_name("", "2026-11-27") == {"name": "", "error": ""}


@needs_ffmpeg
def test_record_stop_and_finish(workspace):
    recorder = recording.Recorder(source_args=tone)
    raw = recorder.start("Warhammer_261127", "ton")
    assert wait_for(lambda: recorder.status()["level"] > -30 and raw.exists() and raw.stat().st_size > 0)
    status = recorder.status()
    assert status["recording"] and status["name"] == "Warhammer_261127" and status["free_hours"] > 0
    with pytest.raises(recording.RecordingError, match="Trwa już"):
        recorder.start("Warhammer_261128", "ton")
    assert recorder.stop() == "Warhammer_261127" and not recorder.status()["recording"]
    assert recording.unfinished() == ["Warhammer_261127"]

    final = recording.finish("Warhammer_261127")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels", "-of", "csv=p=0",
                            str(final)], capture_output=True, text=True, encoding="utf-8").stdout.strip()
    assert final.name == "Warhammer_261127.flac" and probe == "flac,1"
    assert recording.kept_raw_path("Warhammer_261127").exists() and not raw.exists()
    assert recording.unfinished() == []
    with pytest.raises(recording.RecordingError):
        recording.finish("Warhammer_261127")   # nie ma już surowego pliku


@needs_ffmpeg
def test_crashed_recording_can_be_finished(workspace):
    recorder = recording.Recorder(source_args=tone)
    raw = recorder.start("Warhammer_261127", "ton")
    assert wait_for(lambda: raw.exists() and raw.stat().st_size > 20000)
    recorder.process.kill()   # awaria: ffmpeg nie kończy pliku
    recorder.process.wait()
    assert not recorder.status()["recording"] and recording.unfinished() == ["Warhammer_261127"]
    assert recording.duration(recording.finish("Warhammer_261127", "")) > 0.5


@needs_ffmpeg
def test_preview_shows_level_without_file(workspace):
    recorder = recording.Recorder(source_args=tone)
    recorder.preview("ton")
    assert wait_for(lambda: recorder.status()["level"] > -30)
    assert recorder.status()["preview"] and not recorder.status()["recording"]
    recorder.preview("cisza")
    assert wait_for(lambda: recorder.status()["preview"] and recorder.status()["level"] == recording.SILENT_DB
                    and recorder.level_time > 0)
    assert recorder.stop() is None
    assert not recording.originals_dir().exists() or not list(recording.originals_dir().iterdir())


@needs_ffmpeg
def test_window_api(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_CHRONICLER_SETTINGS", str(tmp_path / "ustawienia.toml"))
    monkeypatch.setattr(record_api, "recorder", recording.Recorder(source_args=tone))
    monkeypatch.setattr(recording, "list_devices", lambda: [recording.Device("ton", "Ton")])
    assert record_api.devices()["device"] == "ton"
    assert record_api.start("Warhammer_261127", "ton", True)["recording"]
    assert settings.load()["nagrywanie.wyslij_na_drive"] is True
    assert record_api.stop()["stopped"] == "Warhammer_261127"
    assert record_api.finish_args("Warhammer_261127") == ["record", "Warhammer_261127", "--dokoncz", "--wyslij"]
    assert record_api.status()["unfinished"] == ["Warhammer_261127"]


def test_window_runs_only_post_processing():
    runner = TaskRunner(command=["false"])
    assert "obróbkę" in runner.start("Nagrywanie", ["record", "Warhammer_261127"])


def test_cli_options():
    from rpg_chronicler.cli.parser import build_parser
    args = build_parser().parse_args(["record", "Warhammer_261127", "--dokoncz", "--wyslij"])
    assert (args.session, args.finish, args.upload, args.no_upload) == ("Warhammer_261127", True, True, False)
    assert build_parser().parse_args(["record", "--mikrofony"]).devices
