"""Porządki: pętle Whispera, ostrzeżenie o niezatwierdzonym stanie kampanii, „Uzupełnij brakujące”."""
import json
import os
import time

from rpg_chronicler.maintenance import backfill
from rpg_chronicler import chronicle_pdf, cli, quality, summary
from rpg_chronicler.campaign_tools import memory
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import Segment, Transcript, save_transcript

LOOP = [Segment(10.0 + i, 11.0 + i, "To jest to.", "SPEAKER_00") for i in range(9)]
TRANSCRIPT = Transcript([Segment(0, 5, "Wchodzicie do karczmy.", "SPEAKER_00"), *LOOP,
                         Segment(25, 27, "Co?", "SPEAKER_01"),
                         Segment(30, 32, "To jest to.", "SPEAKER_01")])   # to samo zdanie później zostaje


# --- pętle Whispera ---

def test_remove_loops_keeps_first_of_each_run():
    cleaned, removed = quality.remove_loops(TRANSCRIPT)
    assert removed == 8 and [s.start for s in cleaned.segments] == [0, 10.0, 25, 30]
    assert not quality.find_loops(cleaned) and len(TRANSCRIPT.segments) == 12   # oryginał bez zmian


def test_fix_loops_with_backup_and_undo(workspace, capsys):
    workspace.add_transcript("Fallout_261014", TRANSCRIPT.to_txt())   # starszy format: tylko .txt
    session = list_sessions()[0]
    original = open(session.txt_path, encoding="utf-8").read()

    assert cli.main(["fix-loops", "--dry-run"]) == 0
    assert "Do usunięcia: 8 wypowiedzi" in capsys.readouterr().out and not os.path.exists(session.json_path)

    assert cli.main(["fix-loops"]) == 0
    assert "usunięto 8 powtórzonych" in capsys.readouterr().out
    assert len(session.load_transcript().segments) == 4 and os.path.exists(session.json_path)
    assert len(quality.backups(session)) == 1
    assert cli.main(["fix-loops"]) == 0
    assert "Brak powtórzeń" in capsys.readouterr().out

    assert cli.main(["fix-loops", "Fallout_261014", "--undo"]) == 0
    assert open(session.txt_path, encoding="utf-8").read() == original
    assert not os.path.exists(session.json_path)   # sesja wraca do samego .txt
    assert quality.backups(session) == []


def test_undo_restores_json_too(workspace):
    workspace.add_transcript("Fallout_261014", "")
    session = list_sessions()[0]
    save_transcript(TRANSCRIPT, session.json_path, session.txt_path)
    assert quality.fix_loops(session) == 8
    quality.undo_fix(session)
    assert len(session.load_transcript().segments) == 12
    assert quality.undo_fix(session) is None


# --- niezatwierdzony stan kampanii ---

def test_unaccepted_state_warning(workspace, capsys):
    state = "## Drużyna\n- Fen"
    assert memory.unaccepted_warning("Fallout", "Fallout_261014") is None
    memory.save_proposal("Fallout", memory.State(state, "Fallout_260930"))
    assert "nic jeszcze nie zatwierdzono" in memory.unaccepted_warning("Fallout", "Fallout_261014")
    assert memory.unaccepted_warning("Fallout", "Fallout_260930") is None   # propozycja po tej sesji
    assert memory.unaccepted_warning("Fallout", "Fallout_16_09_2026") is None   # starsza sesja
    memory.save_state("Fallout", state, "Fallout_16_09_2026")
    assert "stan zatwierdzony po sesji Fallout_16_09_2026" in memory.unaccepted_warning("Fallout", "Fallout_261014")

    workspace.add_transcript("Fallout_261014", "[0.00s -> 1.00s] Witajcie.\n")
    summary.summarize_sessions(list_sessions(), interactive=False)
    out = capsys.readouterr().out
    assert "[OSTRZEŻENIE] Kampania Fallout ma niezatwierdzoną propozycję stanu (po sesji Fallout_260930)" in out
    assert "memory Fallout --accept" in out and list_sessions()[0].has_summary   # kronika i tak powstaje


# --- uzupełnianie brakujących ---

def _chronicle(workspace, name):
    workspace.add_transcript(name, "[0.00s -> 1.00s] Witajcie.\n")
    (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(f"# Kronika {name}\n\nTreść.", "utf-8")


def test_backfill_plan(workspace):
    _chronicle(workspace, "Warhammer_261015")
    _chronicle(workspace, "Fallout_261014")
    summary_dir = workspace.dirs["summary"]
    time.sleep(0.01)
    for suffix in ("skrot.txt", "cytaty.txt", "kronika.pdf"):
        (summary_dir / f"Warhammer_261015_{suffix}").write_text("x", encoding="utf-8")
    (summary_dir / "encyklopedia-Warhammer.md").write_text("x", encoding="utf-8")
    (summary_dir / "dziennik-Warhammer-Fen_Wanderer.md").write_text("# Dziennik: Fen Wanderer\n", encoding="utf-8")
    diary_md = str(summary_dir / "dziennik-Warhammer-Fen_Wanderer.md")
    assert backfill.existing_diaries("Warhammer") == [("Fen Wanderer", diary_md)]

    steps = backfill.plan(list_sessions())
    assert [s.label for s in steps] == ["skrót Fallout_261014", "cytaty Fallout_261014", "PDF Fallout_261014",
                                        "encyklopedia Fallout"]   # Warhammer aktualny
    assert backfill.ai_requests(steps) == 3
    assert backfill.summary(steps) == ("skróty: 1 (Fallout_261014)\ncytaty: 1 (Fallout_261014)\n"
                                       "PDF-y: 1 (Fallout_261014)\nencyklopedie: 1 (Fallout)")

    time.sleep(0.01)
    (summary_dir / "Warhammer_261015_podsumowanie.txt").write_text("# Nowa kronika\n\nFen.", "utf-8")
    labels = [s.label for s in backfill.plan(list_sessions())]
    assert "skrót Warhammer_261015" in labels and "encyklopedia Warhammer" in labels
    assert labels[-1] == "dziennik Warhammer (Fen Wanderer)"


def test_backfill_command(workspace, monkeypatch, capsys):
    _chronicle(workspace, "Fallout_261014")
    pdfs = []
    monkeypatch.setattr(chronicle_pdf, "write_pdf", lambda session, path: pdfs.append(path) or open(path, "w").close())
    monkeypatch.setattr(chronicle_pdf, "write_markdown_pdf", lambda text, path, line: pdfs.append(path))
    responses = iter(["Skrót sesji.", json.dumps({"cytaty": [{"kto": "MG", "cytat": "Witajcie."}]}),
                      json.dumps({"hasla": []})])
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or next(responses)

    assert cli.main(["backfill", "--dry-run"]) == 0
    assert "zapytań do AI: ok. 3" in capsys.readouterr().out and not workspace.llm.prompts
    assert cli.main(["backfill"]) == 0
    out = capsys.readouterr().out
    assert "[SUKCES] Uzupełniono: 4 z 4." in out and len(workspace.llm.prompts) == 3
    assert [os.path.basename(p) for p in pdfs] == ["Fallout_261014_kronika.pdf", "encyklopedia-Fallout.pdf"]
    assert backfill.plan(list_sessions()) == []
    assert cli.main(["backfill"]) == 0
    assert "Wszystko jest aktualne" in capsys.readouterr().out
