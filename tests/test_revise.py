import pytest

from rpg_chronicler import chronicle, cli, revision
from rpg_chronicler.session import list_sessions

LEGACY = "[0.00s -> 2.00s]  Hans otworzył drzwi.\n"
CHRONICLE = "# Kronika\n\nHans otworzył drzwi karczmy i spotkał karczmarza, który opowiedział o zaginięciach.\n"


@pytest.fixture
def session(workspace):
    workspace.add_transcript("Warhammer_261001", LEGACY)
    (workspace.dirs["summary"] / "Warhammer_261001_podsumowanie.txt").write_text(CHRONICLE, encoding="utf-8")
    return list_sessions()[0]


def test_revise_saves_previous_version_and_uses_transcript(workspace, session):
    revised = CHRONICLE.replace("Hans", "Hanna")
    workspace.llm.response = revised
    revision.revise_chronicle(workspace.llm, session, "to nie Hans, tylko Hanna")

    prompt = workspace.llm.prompts[0]
    assert "to nie Hans, tylko Hanna" in prompt and "Hans otworzył drzwi." in prompt   # transkrypcja jako źródło
    assert prompt.index("<kronika") < prompt.index("Polecenie użytkownika")           # kronika na początku
    assert chronicle.read_chronicle(session) == revised.strip() + "\n"
    assert len(chronicle.previous_versions(session)) == 1

    assert cli.main(["revise", "Warhammer_261001", "--undo"]) == 0
    assert chronicle.read_chronicle(session) == CHRONICLE
    assert chronicle.previous_versions(session) == []
    assert cli.main(["revise", "Warhammer_261001", "--undo"]) == 1


def test_revise_prefers_events_list(workspace, session):
    (workspace.dirs["summary"] / "Warhammer_261001_wydarzenia.md").write_text("WYDARZENIA SESJI", encoding="utf-8")
    workspace.llm.response = CHRONICLE
    revision.revise_chronicle(workspace.llm, session, "popraw")
    assert "WYDARZENIA SESJI" in workspace.llm.prompts[0] and "Hans otworzył drzwi." not in workspace.llm.prompts[0]


def test_revise_refuses_truncated_answer(workspace, session):
    workspace.llm.response = "Hanna."
    with pytest.raises(revision.RevisionError):
        revision.revise_chronicle(workspace.llm, session, "to nie Hans, tylko Hanna")
    assert chronicle.read_chronicle(session) == CHRONICLE and chronicle.previous_versions(session) == []


def test_revise_command_needs_instruction(session, capsys):
    assert cli.main(["revise", "Warhammer_261001"]) == 1
    assert "Podaj polecenie" in capsys.readouterr().err
