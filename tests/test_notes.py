"""Sesje bez nagrania: kronika z notatek MG (`add-session`, notes.py)."""
import datetime
import os
import time

import pytest

from rpg_chronicler import after_chronicle, campaigns, cli, notes, revision, search, summary
from rpg_chronicler.maintenance import backfill
from rpg_chronicler.campaign_tools import diary
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.web.text import session_stage
from rpg_chronicler.session import list_sessions

NOTES = "- Drużyna dotarła do Ubersreiku.\n- Fen kupił linę u kupca Hansa.\n- Most na Reiku zawalony.\n"
CAMPAIGN = Campaign(key="Warhammer", system="Warhammer Fantasy",
                    player_characters={"Fen Wanderer": "", "Eustachos": ""})


@pytest.fixture
def notes_file(tmp_path):
    path = tmp_path / "notatki.md"
    path.write_text(NOTES, encoding="utf-8")
    return str(path)


def test_parse_and_format_roundtrip():
    original = notes.Notes("- punkt 1\n- punkt 2", ("Fen Wanderer", "Sir Amos"))
    content = notes.format_notes(original)
    assert content.startswith("<!-- obecni: Fen Wanderer, Sir Amos -->\n\n- punkt 1")
    assert notes.parse(content) == original
    assert notes.parse("- tylko punkty\r\n") == notes.Notes("- tylko punkty")
    assert notes.format_notes(notes.Notes("x")) == "x\n"
    assert "Obecne postacie graczy: Fen Wanderer, Sir Amos" in notes.for_llm(original)


def test_session_name_and_conflicts(workspace):
    assert notes.session_name("Warhammer", datetime.date(2026, 11, 16)) == "Warhammer_261116"
    for bad in ("", "Moja kampania", "War_hammer"):
        with pytest.raises(notes.NotesError):
            notes.session_name(bad, datetime.date(2026, 11, 16))
    workspace.add_transcript("Warhammer_261116", "[0.00s -> 1.00s] Witajcie.\n")
    with pytest.raises(notes.NotesError, match="już istnieje"):
        notes.check_new_name("Warhammer_261116")
    with pytest.raises(notes.NotesError, match="nie ma daty"):
        notes.check_new_name("Warhammer_sesja")
    notes.check_new_name("Warhammer_261117")


def test_add_session_command(workspace, notes_file, capsys):
    args = ["add-session", "Warhammer_261116", "--plik", notes_file]
    assert cli.main(args + ["--obecni", "Fen Wanderer, Eustachos"]) == 0
    assert "summarize Warhammer_261116" in capsys.readouterr().out
    [session] = list_sessions()
    assert session.has_notes and session.has_source and not session.has_transcript and session.audio_path is None
    assert notes.read_notes(session) == notes.Notes(NOTES.strip(), ("Fen Wanderer", "Eustachos"))
    assert session_stage(session) == ("z notatek · czeka na kronikę", False)

    assert cli.main(["add-session", "Warhammer_261116", "--plik", notes_file]) == 1   # sesja już jest
    assert "już istnieje" in capsys.readouterr().err
    with open(notes_file, "w", encoding="utf-8") as f:
        f.write("- Nowy punkt.")
    assert cli.main(["add-session", "Warhammer_261116", "--plik", notes_file, "--replace"]) == 0
    assert notes.read_notes(session) == notes.Notes("- Nowy punkt.", ("Fen Wanderer", "Eustachos"))  # obecni zostają

    assert cli.main(["status"]) == 0
    assert "notatki" in capsys.readouterr().out


def test_summarize_from_notes(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Warhammer": CAMPAIGN})
    monkeypatch.setattr(after_chronicle, "CHRONICLE_QUOTES", True)
    monkeypatch.setattr(after_chronicle, "CHRONICLE_BRIEF", True)
    notes.save_notes("Warhammer_261116", notes.Notes(NOTES, ("Fen Wanderer",)))
    workspace.llm.response = "📜 Kronika Sesji [Warhammer Fantasy]: Zawalony most\n\nDotarliście do Ubersreiku."

    summary.summarize_sessions(list_sessions(), interactive=False)   # bez mówców i bez --allow-unnamed
    [session] = list_sessions()
    assert session.has_summary
    prompt = workspace.llm.prompts[0]
    assert "notatek Mistrza Gry" in prompt and "NIE WYMYŚLAJ" in prompt and "{" not in prompt
    assert "<notatki_mg>\nObecne postacie graczy: Fen Wanderer\n\n- Drużyna dotarła do Ubersreiku." in prompt
    assert len(workspace.llm.prompts) == 2   # kronika + skrót, bez cytatów
    assert "Fen Wanderer" == after_chronicle.session_characters(session)[0]
    assert session_stage(session) == ("z notatek · gotowe", True)

    time.sleep(0.01)
    notes.save_notes(session.name, notes.Notes("- Poprawka.", ("Fen Wanderer",)))
    assert notes.chronicle_is_stale(session)
    assert session_stage(session) == ("z notatek · notatki nowsze niż kronika", False)


def test_notes_used_by_revision_search_diary_and_backfill(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Warhammer": CAMPAIGN})
    notes.save_notes("Warhammer_261116", notes.Notes(NOTES, ("Fen Wanderer",)))
    (workspace.dirs["summary"] / "Warhammer_261116_podsumowanie.txt").write_text(
        "# Kronika: Most\n\nDrużyna przeprawiła się przez rzekę.", encoding="utf-8")
    [session] = list_sessions()

    source, note = revision.revision_source(session)
    assert "kupca Hansa" in source and "notatki Mistrza Gry" in note

    hits = search.search(list_sessions(), "kupiec")
    assert [(h.kind, h.text) for h in hits] == [(search.KIND_NOTES, "- Fen kupił linę u kupca Hansa.")]
    assert search.search(list_sessions(), "kupiec", transcripts=False) == []

    assert [s.name for s, _ in diary.diary_sessions(CAMPAIGN, "Fen Wanderer", list_sessions())] == [session.name]
    assert diary.diary_sessions(CAMPAIGN, "Eustachos", list_sessions()) == []

    labels = [s.label for s in backfill.plan(list_sessions())]
    assert "skrót Warhammer_261116" in labels and not any(label.startswith("cytaty") for label in labels)


def test_pdf_and_discord_annotation(workspace, notes_file, monkeypatch, capsys):
    pytest.importorskip("markdown")
    from rpg_chronicler import chronicle, chronicle_pdf, discord
    from rpg_chronicler.cli import chronicles

    assert cli.main(["add-session", "Warhammer_261116", "--plik", notes_file]) == 0
    (workspace.dirs["summary"] / "Warhammer_261116_podsumowanie.txt").write_text("# Kronika: Most\n\nTreść.", "utf-8")
    [session] = list_sessions()
    html = chronicle_pdf.chronicle_html("# Kronika: Most\n\nTreść.", session)
    assert '<div class="date">Sesja z 16 listopada 2026 · spisana z notatek Mistrza Gry</div>' in html

    sent = {}
    monkeypatch.setattr(chronicles, "ensure_pdf", lambda s: os.devnull)
    monkeypatch.setattr(chronicle, "webhook_for", lambda key: "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(discord, "send", lambda url, message, pdf: sent.update(message=message) or "1")
    workspace.llm.response = "Zapowiedź."
    assert cli.main(["discord", "Warhammer_261116"]) == 0, capsys.readouterr().out
    footer = sent["message"]["embeds"][0]["footer"]["text"]
    assert footer.endswith("16 listopada 2026 · spisana z notatek Mistrza Gry"), footer
