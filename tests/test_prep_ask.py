"""Przed sesją („Poprzednio w kampanii…”, notatki MG) i „Zapytaj kronikarza” (prep.py, ask.py)."""
import os
import time

import pytest

from rpg_chronicler import ask, campaigns, chronicle, cli, discord, encyclopedia, memory, prep
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.glossary import chronicles_for
from rpg_chronicler.prompts import chronicle_blocks
from rpg_chronicler.session import list_sessions

CAMPAIGN = Campaign("Warhammer", "Warhammer Fantasy", context="Reikland.", player_characters={"Fen": ""})


@pytest.fixture
def chronicles(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Warhammer": CAMPAIGN})
    for name, text in (("Warhammer_261015", "Fen kupił linę."), ("Warhammer_261105", "Drużyna zeszła do krypty.")):
        workspace.add_transcript(name, "[0.00s -> 1.00s] Witajcie.\n")
        (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(text, encoding="utf-8")
        time.sleep(0.01)
    memory.save_state("Warhammer", "## Otwarte wątki\n- Kult w Ubersreiku", "Warhammer_261105")
    return workspace


def test_recap_written_and_current(chronicles, capsys):
    chronicles.llm.response = "Poprzednio… zeszliście do krypty."
    assert cli.main(["recap", "Warhammer"]) == 0
    path = prep.recap_path("Warhammer")
    assert prep.read(path) == ("Warhammer_261105", "Poprzednio… zeszliście do krypty.")
    assert prep.is_current(path, "Warhammer", list_sessions())
    prompt = chronicles.llm.prompts[0]
    assert prompt.startswith('<kronika sesja="Warhammer_261105">') and "Fen kupił" not in prompt  # tylko ostatnia
    assert "Kult w Ubersreiku" in prompt and "Reikland." in prompt and "{" not in prompt
    assert cli.main(["recap", "Warhammer"]) == 0                     # aktualny - bez nowego zapytania
    assert len(chronicles.llm.prompts) == 1

    time.sleep(0.01)
    (chronicles.dirs["summary"] / "Warhammer_261105_podsumowanie.txt").write_text("Nowa wersja.", encoding="utf-8")
    assert not prep.is_current(path, "Warhammer", list_sessions())  # kronika nowsza niż tekst


def test_recap_to_discord(chronicles, monkeypatch):
    sent = []
    monkeypatch.setattr(chronicle, "webhook_for", lambda key: "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(discord, "send", lambda url, message, file_path=None: sent.append(message) or "1")
    chronicles.llm.response = "Poprzednio…"
    assert cli.main(["recap", "Warhammer", "--discord"]) == 0
    embed = sent[0]["embeds"][0]
    assert embed["title"] == "Poprzednio w kampanii Warhammer…" and embed["description"] == "Poprzednio…"
    assert "po Warhammer_261105" in embed["footer"]["text"] and "attachments" not in sent[0]


def test_gm_notes_share_prefix_with_encyclopedia(chronicles, monkeypatch):
    from rpg_chronicler import chronicle_pdf
    pdfs = []
    monkeypatch.setattr(chronicle_pdf, "write_markdown_pdf", lambda text, path, line: pdfs.append(path))
    chronicles.llm.response = "## Otwarte wątki\n- Kult (Warhammer_261105)"
    assert cli.main(["gm-notes", "Warhammer"]) == 0
    after, text = prep.read(prep.gm_notes_path("Warhammer"))
    assert after == "Warhammer_261105" and text.startswith("# Notatki MG: Warhammer")
    assert "tylko dla Mistrza Gry" in text and "- Kult (Warhammer_261105)" in text
    assert pdfs == [prep.gm_notes_pdf_path("Warhammer")]
    shared = chronicle_blocks(chronicles_for("Warhammer", list_sessions()), encyclopedia.CHRONICLES_LIMIT)
    assert chronicles.llm.prompts[0].startswith(shared)                 # ten sam początek co encyklopedia


def test_ask_with_session_references_and_history(chronicles, capsys):
    chronicles.llm.response = ("Linę kupił Fen [Warhammer_261015]. "
                               "Kryptę zbadaliście później [Warhammer_261105, Nie_ma].")
    assert cli.main(["ask", "Warhammer", "Kto kupił linę?"]) == 0
    assert "Sesje: Warhammer_261015, Warhammer_261105" in capsys.readouterr().out
    assert "Pytanie: Kto kupił linę?" in chronicles.llm.prompts[0]
    [answer] = ask.load_history("Warhammer")
    assert answer.question == "Kto kupił linę?" and answer.sessions == ["Warhammer_261015", "Warhammer_261105"]
    for i in range(ask.HISTORY_LIMIT + 2):
        ask.ask(chronicles.llm, CAMPAIGN, list_sessions(), f"Pytanie {i}")
    history = ask.load_history("Warhammer")
    assert len(history) == ask.HISTORY_LIMIT and history[0].question == f"Pytanie {ask.HISTORY_LIMIT + 1}"
    ask.remove_from_history("Warhammer", 0)
    assert ask.load_history("Warhammer")[0].question == f"Pytanie {ask.HISTORY_LIMIT}"


def test_without_chronicles(workspace, capsys):
    assert cli.main(["recap", "Zakon"]) == 1 and cli.main(["ask", "Zakon", "Co?"]) == 1
    assert "nie ma jeszcze żadnej kroniki" in capsys.readouterr().err
    assert not os.path.exists(prep.recap_path("Zakon"))
