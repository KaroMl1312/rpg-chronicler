"""Nowe okno (web/): dane z API, zabezpieczenia serwera i zadania w tle - bez przeglądarki."""
import json
import sys
import time
import urllib.error
import urllib.request

import pytest

from rpg_chronicler import envfile, progress
from rpg_chronicler.web import api
from rpg_chronicler.web.server import App, start_server
from rpg_chronicler.web.tasks import TaskRunner

TRANSCRIPT = "[SPEAKER_00] [0.00s -> 2.00s] Wchodzicie do karczmy.\n[SPEAKER_01] [2.00s -> 3.00s] Zamawiam piwo.\n"


def test_state_and_session_detail(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    (workspace.dirs["summary"] / "Warhammer_261015_podsumowanie.txt").write_text(
        "# Kronika: Karczma\n\n> „Piwo!”\n\nTekst <script>alert(1)</script> i **pogrubienie**.", encoding="utf-8")
    workspace.add_audio("Fallout_261020")

    state = api.state()
    assert [s["name"] for s in state["sessions"]] == ["Fallout_261020", "Warhammer_261015"]
    assert state["filters"][0]["label"] == "Wszystkie (2)"

    detail = api.session_detail("Warhammer_261015")
    assert detail["title"] == "Kronika: Karczma"
    assert "<blockquote>" in detail["chronicle_html"] and "<strong>pogrubienie</strong>" in detail["chronicle_html"]
    assert "<script>" not in detail["chronicle_html"] and "&lt;script&gt;" in detail["chronicle_html"]
    assert detail["unnamed_speakers"] is True
    assert api.session_detail("Fallout_261020")["stage"] == "czeka na transkrypcję"


def test_transcript_blocks_with_speaker_colors(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    (workspace.dirs["txt"] / "Warhammer_261015.mowcy.json").write_text('{"SPEAKER_00": "MG", "SPEAKER_01": "Fen"}',
                                                                        encoding="utf-8")
    data = api.transcript("Warhammer_261015")
    assert data["kind"] == "transkrypcja"
    assert [(b["speaker"], b["color"], b["time"]) for b in data["blocks"]] == [("MG", 0, "0:00:00"), ("Fen", 1, "0:00:02")]


def test_settings_and_keys(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv(envfile.ENV_VAR, str(tmp_path / ".env"))
    payload = api.settings_payload()
    assert payload["groups"][0]["fields"][0]["key"] == "ai.dostawca"
    assert [k["name"] for s in payload["keys"] for k in s["keys"]][0] == "HUGGINGFACE_TOKEN"

    assert api.save_key("HUGGINGFACE_TOKEN", " abc ")["warning"].startswith("Token Hugging Face zwykle")
    assert envfile.read()["HUGGINGFACE_TOKEN"] == "abc"
    with pytest.raises(ValueError):
        api.save_key("PATH", "x")
    with pytest.raises(ValueError):
        api.save_setting("google_drive.nagrania", "bez-dwukropka")
    with pytest.raises(ValueError):
        api.save_setting("nieznane.pole", 1)


def test_openable_only_inside_data_folders(workspace, tmp_path):
    inside = workspace.dirs["summary"] / "kronika.pdf"
    inside.write_bytes(b"%PDF")
    outside = tmp_path / "inny.pdf"
    outside.write_bytes(b"%PDF")
    assert api.openable(str(inside))
    assert not api.openable(str(outside))


def _request(url, token=None, body=None, host=None):
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    if token:
        request.add_header("X-Token", token)
    if host:
        request.add_header("Host", host)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_requires_token_and_local_host(workspace):
    app = App()
    server, url = start_server(app)
    base = url.split("#")[0].rstrip("/")
    try:
        assert _request(base + "/")[0] == 200                        # strona bez klucza (sama w sobie nic nie zdradza)
        assert _request(base + "/static/../server.py")[0] == 404      # poza folderem static
        assert _request(base + "/api/state")[0] == 403                # API bez klucza
        assert _request(base + "/api/state", "zly")[0] == 403
        port = base.rsplit(":", 1)[1]
        assert _request(base + "/api/state", app.token, host=f"evil.example:{port}")[0] == 403   # DNS rebinding
        status, body = _request(base + "/api/state", app.token)
        assert status == 200 and json.loads(body)["sessions"] == []
        status, body = _request(base + "/api/session?name=Nie_ma", app.token)
        assert status == 400 and "Nie_ma" in json.loads(body)["error"]
        status, body = _request(base + "/api/task", app.token, {"title": "x", "args": ["rm", "-rf"]})
        assert json.loads(body)["error"].startswith("Nieznana komenda")
    finally:
        server.shutdown()


def test_task_runner_reports_progress_lines_and_end(tmp_path):
    script = tmp_path / "zadanie.py"
    script.write_text(
        "import os, sys\n"
        f"assert os.environ['{progress.ENV_VAR}'] == 'json'\n"
        "print('pierwsza linia')\n"
        f"print('{progress.PREFIX}' + '{{\"etap\": \"transkrypcja\", \"zrobione\": 1, \"razem\": 4}}')\n"
        "print('pobieranie 50%', end='\\r', flush=True)\n"
        "print('Zażółć gęślą jaźń')\n"
        "sys.exit(3)\n", encoding="utf-8")
    runner = TaskRunner([sys.executable, str(script)])
    assert runner.start("Próba", ["status"]) is None
    assert runner.start("Druga", ["status"]) == "Inne zadanie jest w toku."
    deadline = time.time() + 20
    while runner.running and time.time() < deadline:
        time.sleep(0.05)
    snap = runner.snapshot(0)
    assert snap["lines"][:3] == ["$ rpg-chronicler status", "pierwsza linia", "Zażółć gęślą jaźń"]
    assert snap["progress"] == {"stage": "transkrypcja", "session": "", "fraction": 0.25}
    assert snap["status"] == "pobieranie 50%"
    assert snap["finished"]["success"] is False and snap["finished"]["description"] == "błąd (kod 3)"
    assert runner.snapshot(snap["seq"])["lines"] == []
    assert runner.start("Zła", ["rm"]).startswith("Nieznana komenda")
