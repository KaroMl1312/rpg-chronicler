import os

from rpg_chronicler import chronicle, cli, summary
from rpg_chronicler.chronicle_pdf import chronicle_html
from rpg_chronicler.session import list_sessions

LEGACY = "[0.00s -> 1.00s] Wchodzicie do karczmy.\n"
BRIEF = "Uwarzyliście lek, a potem ruszyliście na północ. Sesja skończyła się w Dolinie."


def test_brief_written_after_new_chronicle(workspace, monkeypatch):
    monkeypatch.setattr(summary, "CHRONICLE_BRIEF", True)
    responses = iter(["PEŁNA KRONIKA", BRIEF])
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or next(responses)
    workspace.add_transcript("Warhammer_261015", LEGACY)

    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    session = list_sessions()[0]
    assert "PEŁNA KRONIKA" in workspace.llm.prompts[1] and "Jeden akapit ciągłej opowieści" in workspace.llm.prompts[1]
    assert chronicle.read_brief(session) == BRIEF
    assert chronicle.brief_is_current(session)


def test_cli_brief_only_missing_or_stale(workspace):
    for name in ("Warhammer_261001", "Warhammer_261015"):
        workspace.add_transcript(name, LEGACY)
        (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(f"KRONIKA {name}", encoding="utf-8")
    workspace.llm.response = BRIEF
    assert cli.main(["brief"]) == 0
    assert len(workspace.llm.prompts) == 2

    assert cli.main(["brief"]) == 0          # wszystkie aktualne - bez zapytań
    assert len(workspace.llm.prompts) == 2

    stale = list_sessions(["Warhammer_261015"])[0]
    later = os.path.getmtime(chronicle.brief_path(stale)) + 10
    os.utime(stale.summary_path, (later, later))  # kronikę wygenerowano ponownie po skrócie
    assert not chronicle.brief_is_current(stale)
    assert cli.main(["brief"]) == 0
    assert len(workspace.llm.prompts) == 3 and "KRONIKA Warhammer_261015" in workspace.llm.prompts[2]


def test_pdf_starts_with_brief(workspace):
    workspace.add_transcript("Warhammer_261015", LEGACY)
    (workspace.dirs["summary"] / "Warhammer_261015_podsumowanie.txt").write_text("# Kronika\n\nTreść.", encoding="utf-8")
    session = list_sessions()[0]
    assert "W skrócie" not in chronicle_html("# Kronika\n\nTreść.", session)
    with open(chronicle.brief_path(session), "w", encoding="utf-8") as f:
        f.write(BRIEF)
    document = chronicle_html("# Kronika\n\nTreść.", session)
    assert 'class="brief"' in document and "<p>Uwarzyliście lek, a potem ruszyliście na północ." in document
    assert document.index("W skrócie") < document.index("Treść.")
