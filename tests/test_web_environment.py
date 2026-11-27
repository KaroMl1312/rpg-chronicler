"""Baner „.venv nie działa”: sprawdzenie bibliotek transkrypcji w osobnym procesie."""
from rpg_chronicler.web import api, environment


def test_check_reports_last_line_of_import_error(monkeypatch):
    monkeypatch.setattr(environment, "modules", lambda: ["json"])
    assert environment.check() is None
    monkeypatch.setattr(environment, "modules", lambda: ["json", "modul_ktorego_nie_ma"])
    assert "modul_ktorego_nie_ma" in environment.check()


def test_status_in_window_state(monkeypatch):
    monkeypatch.setitem(environment._result, "error", None)
    assert api.state()["environment"] is None
    monkeypatch.setitem(environment._result, "error", "ModuleNotFoundError: No module named 'torch'")
    status = api.state()["environment"]
    assert "torch" in status["error"] and status["hint"] and status["folder"]
