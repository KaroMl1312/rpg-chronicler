import os

from rpg_chronicler.session import list_sessions


def test_finds_audio_with_uppercase_extension(workspace):
    workspace.add_audio("Zakon_1", ".FLAC")
    workspace.add_audio("Zakon_2", ".flac")

    sessions = list_sessions()
    assert [s.name for s in sessions] == ["Zakon_1", "Zakon_2"]
    assert os.path.basename(sessions[0].audio_path) == "Zakon_1.FLAC"


def test_select_session_by_filename_with_uppercase_extension(workspace):
    workspace.add_audio("Zakon_1", ".FLAC")

    assert list_sessions(["Zakon_1.FLAC"])[0].name == "Zakon_1"


def test_duplicate_recordings_pick_first_supported_ext_and_warn(workspace, capsys):
    workspace.add_audio("Warhammer_1", ".flac")
    workspace.add_audio("Warhammer_1", ".m4a")

    (session,) = list_sessions()
    assert os.path.basename(session.audio_path) == "Warhammer_1.m4a"
    assert "[OSTRZEŻENIE] Sesja Warhammer_1 ma kilka nagrań" in capsys.readouterr().out


def test_missing_audio_dir_is_not_an_error(workspace):
    workspace.dirs["audio"].rmdir()
    workspace.add_transcript("Fallout_1", "[0.00s -> 1.00s] tekst")

    (session,) = list_sessions()
    assert session.audio_path is None
