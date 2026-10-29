import json

from rpg_chronicler import cli

TRANSCRIPT = "[SPEAKER_00] [0.00s -> 2.00s]  Witajcie.\n[SPEAKER_01] [2.00s -> 3.50s]  Dzień dobry.\n"


def test_no_command_runs_full_pipeline():
    args = cli.build_parser().parse_args([])
    assert args.func is cli.cmd_run and not args.offline


def test_status_lists_sessions(workspace, capsys):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    workspace.add_audio("Fallout_2")
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Warhammer_1" in out and "Fallout_2" in out
    assert "rpg-chronicler migrate" in out  # Warhammer_1 ma tylko starszy .txt


def test_unknown_session_returns_error(workspace, capsys):
    assert cli.main(["status", "nie-ma"]) == 1
    assert "Nie znaleziono sesji" in capsys.readouterr().err


def test_migrate_writes_json_and_keeps_txt(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    txt = workspace.dirs["txt"] / "Warhammer_1.txt"
    json_path = workspace.dirs["txt"] / "Warhammer_1.transkrypcja.json"

    assert cli.main(["migrate", "--dry-run"]) == 0
    assert not json_path.exists()

    assert cli.main(["migrate"]) == 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert [s["speaker"] for s in data["segments"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert data["duration"] == 3.5
    assert txt.read_text(encoding="utf-8") == TRANSCRIPT


def test_summarize_non_interactive_from_cli(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    assert cli.main(["summarize", "--no-interactive", "--allow-unnamed"]) == 0
    assert (workspace.dirs["summary"] / "Warhammer_1_podsumowanie.txt").read_text(encoding="utf-8") == "KRONIKA"
