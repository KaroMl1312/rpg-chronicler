import subprocess

from rpg_chronicler.storage import drive


def record_rclone(monkeypatch, fail_on=None):
    calls = []

    def run(cmd, check):
        calls.append(cmd)
        if fail_on and fail_on in cmd:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(drive.subprocess, "run", run)
    return calls


def test_sync_pulls_transcripts_summaries_and_audio(monkeypatch, tmp_path):
    for name in ("AUDIO_DIR", "TXT_DIR", "SUMMARY_DIR"):
        monkeypatch.setattr(drive, name, str(tmp_path / name))
    calls = record_rclone(monkeypatch)
    drive.sync_from_gdrive()
    sources = [cmd[2] for cmd in calls]
    assert sources == [drive.RCLONE_TXT_REMOTE, drive.RCLONE_SUMMARY_REMOTE, drive.RCLONE_AUDIO_REMOTE]


def test_upload_continues_after_failure(monkeypatch, capsys):
    calls = record_rclone(monkeypatch, fail_on=drive.RCLONE_TXT_REMOTE)
    drive.upload_to_gdrive()
    assert [cmd[3] for cmd in calls] == [drive.RCLONE_TXT_REMOTE, drive.RCLONE_SUMMARY_REMOTE]
    out = capsys.readouterr().out
    assert "Nie udało się wysłać transkrypcji" in out and "Podsumowania wysłane" in out
