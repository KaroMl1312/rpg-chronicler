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


# --- etap 2: praca z sesją ---

from rpg_chronicler import notes  # noqa: E402
from rpg_chronicler.web import session_api  # noqa: E402


def test_speakers_rows_and_save(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    data = session_api.speakers("Warhammer_261015")
    assert data["state"] == "ok"
    assert {r["label"] for r in data["rows"]} == {"SPEAKER_00", "SPEAKER_01"}
    assert data["names"][0]["name"] == "MG"
    with pytest.raises(ValueError):
        session_api.save_speakers("Warhammer_261015", {"SPEAKER_00": "  "})
    session_api.save_speakers("Warhammer_261015", {"SPEAKER_00": "MG", "SPEAKER_01": "Fen", "SPEAKER_99": "obcy"})
    saved = json.loads((workspace.dirs["txt"] / "Warhammer_261015.mowcy.json").read_text(encoding="utf-8"))
    assert saved == {"SPEAKER_00": "MG", "SPEAKER_01": "Fen"}
    assert api.session_detail("Warhammer_261015")["unnamed_speakers"] is False


def test_notes_new_session_name_and_save(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    assert session_api.notes_name("Warhammer", "2026-10-15")["error"].startswith("Sesja Warhammer_261015 już istnieje")
    info = session_api.notes_name("Warhammer", "2026-11-30")
    assert info == {"name": "Warhammer_261130", "error": "", "characters": []}
    result = session_api.save_notes(None, "Warhammer", "2026-11-30", "- Drużyna dotarła do miasta.", ["Fen"])
    assert result["name"] == "Warhammer_261130"
    saved = notes.read_notes(api.find_session("Warhammer_261130"))
    assert saved.present == ("Fen",) and "dotarła" in saved.text
    with pytest.raises(ValueError):
        session_api.save_notes(None, "Warhammer", "2026-12-01", "   ", [])


def test_search_and_delete_plan(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    (workspace.dirs["summary"] / "Warhammer_261015_podsumowanie.txt").write_text("Drużyna w karczmie.", encoding="utf-8")
    result = session_api.run_search("karczma", None, True, True)
    kinds = [h["kind"] for h in result["hits"]]
    assert kinds == ["kronika", "transkrypcja"] and "<b>karczmie</b>" in result["hits"][0]["html"]
    assert session_api.run_search("karczma", None, False, True)["hits"][0]["tab"] == "transkrypcja"
    plan = session_api.delete_plan("Warhammer_261015", "kronika")
    assert plan["heading"] == "Usunąć kronikę?" and "Warhammer_261015_podsumowanie.txt" in plan["files"]
    assert session_api.delete_plan("Warhammer_261015", "sesja")["confirm"]
    options = {o["scope"]: o["enabled"] for o in session_api.delete_options("Warhammer_261015")}
    assert options == {"kronika": True, "od-nowa": False, "sesja": True}


def test_audio_served_with_ranges(workspace):
    workspace.add_transcript("Warhammer_261015", TRANSCRIPT)
    (workspace.dirs["audio"] / "Warhammer_261015.m4a").write_bytes(bytes(range(256)) * 4)
    app = App()
    server, url = start_server(app)
    base = url.split("#")[0].rstrip("/")
    try:
        audio = f"{base}/api/audio?name=Warhammer_261015&t={app.token}"
        request = urllib.request.Request(audio, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 206 and response.read() == bytes(range(10, 20))
            assert response.headers["Content-Range"] == "bytes 10-19/1024"
            assert response.headers["Content-Type"] == "audio/mp4"
        assert _request(f"{base}/api/audio?name=Warhammer_261015")[0] == 403       # bez klucza
        assert _request(f"{base}/api/audio?name=Nie_ma&t={app.token}")[0] == 404
    finally:
        server.shutdown()
