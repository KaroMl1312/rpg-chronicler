import os

import pytest

from rpg_chronicler import campaigns, cli
from rpg_chronicler.campaign_tools import diary
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import Segment, Transcript, save_speaker_mapping

CAMPAIGN = Campaign(key="Warhammer", system="Warhammer Fantasy", context="Reikland, rok 2512.",
                    player_characters={"Fen Wanderer": "", "Eustachos": "Ania", "Sir Amos": ""})


@pytest.fixture
def chronicles(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Warhammer": CAMPAIGN})
    summary = workspace.dirs["summary"]
    (summary / "Warhammer_261015_podsumowanie.txt").write_text(
        "📜 Kronika Sesji [Warhammer]: Most\n\nFen przekradł się przez most.", encoding="utf-8")
    (summary / "Warhammer_260918_podsumowanie.txt").write_text(
        "📜 Kronika Sesji [Warhammer]: Karczma\n\nDrużyna piła w karczmie.", encoding="utf-8")
    (summary / "Warhammer_261105_podsumowanie.txt").write_text(
        "Kronika Sesji: Wieża\n\nEustachos sam wspiął się na wieżę.", encoding="utf-8")
    (summary / "Fallout_261014_podsumowanie.txt").write_text("Fen w Megatonie.", encoding="utf-8")
    (summary / "Warhammer_261015_cytaty.txt").write_text("„Cicho!” — Fen\n„Ja nie” — MG\n", encoding="utf-8")
    (summary / "Warhammer_261015_wydarzenia.md").write_text("## Część 1\n- most nad Reikiem\n", encoding="utf-8")
    # Na sesji z karczmą Fen mówił (gracz → postać przez mapowanie), choć kronika go nie wymienia
    for name in ("Warhammer_261015", "Warhammer_261105", "Fallout_261014"):
        workspace.add_transcript(name, Transcript([Segment(0, 2, "Hej.", "SPEAKER_00")]).to_txt())
    workspace.add_transcript("Warhammer_260918", Transcript([Segment(0, 2, "Piwo!", "SPEAKER_01")]).to_txt())
    save_speaker_mapping(str(workspace.dirs["txt"] / "Warhammer_260918.txt"), {"SPEAKER_01": "fen"})
    return workspace


def test_diary_sessions_presence_and_prompt(chronicles):
    selected = diary.diary_sessions(CAMPAIGN, "Fen Wanderer", list_sessions())
    assert [s.name for s, _ in selected] == ["Warhammer_260918", "Warhammer_261015"]   # bez wieży i Fallouta
    session, chronicle = selected[1]
    prefix, prompt = diary.entry_prompt(session, CAMPAIGN, "Fen Wanderer", chronicle, previous="Wczoraj padało.")
    assert prefix.startswith('<kronika sesja="Warhammer_261015">') and "most nad Reikiem" in prefix
    assert "dziennika postaci Fen Wanderer (w materiale także: Fen, Wanderer)" in prompt
    assert "- „Cicho!”" in prompt and "Ja nie" not in prompt          # cytat „— Fen” to ta postać
    assert "<poprzedni_wpis>\nWczoraj padało.\n</poprzedni_wpis>" in prompt
    assert "Reikland, rok 2512." in prompt and "{" not in prompt
    assert "poprzedni_wpis" not in diary.entry_prompt(session, CAMPAIGN, "Fen Wanderer", chronicle)[1]
    assert diary.aliases("Sir Amos") == ["Sir Amos", "Amos"] and diary.aliases("Fen") == ["Fen"]
    assert diary.canonical_character(CAMPAIGN, "fen") == "Fen Wanderer"
    assert diary.canonical_character(CAMPAIGN, "eustachos") == "Eustachos"
    assert diary.canonical_character(CAMPAIGN, "Hans") == "Hans"
    assert diary.pdf_path("Warhammer", "Sir Amos").endswith("dziennik-Warhammer-Sir_Amos.pdf")


def test_build_uses_cache_and_skips_absent(chronicles):
    fake = chronicles.llm
    fake.response = "Piłem z towarzyszami."
    text = diary.build(lambda: fake, CAMPAIGN, "Fen Wanderer", list_sessions())
    assert text.startswith("# Dziennik: Fen Wanderer\n") and "wpisy: 2" in text
    assert "## 18.09.2026 — Karczma\n\nPiłem z towarzyszami." in text and "## 15.10.2026 — Most" in text
    assert len(fake.prompts) == 2
    assert "poprzedni_wpis" not in fake.prompts[0] and "Piłem z towarzyszami." in fake.prompts[1]
    diary.build(lambda: fake, CAMPAIGN, "Fen Wanderer", list_sessions())
    assert len(fake.prompts) == 2                     # wpisy z cache
    diary.build(lambda: fake, CAMPAIGN, "Fen Wanderer", list_sessions(), force=True)
    assert len(fake.prompts) == 4

    fake.response = "BRAK."
    with pytest.raises(diary.DiaryError):
        diary.build(lambda: fake, CAMPAIGN, "Eustachos", list_sessions())
    with pytest.raises(diary.DiaryError):
        diary.build(lambda: fake, CAMPAIGN, "Nikt", list_sessions())


def test_diary_command_writes_markdown_and_pdf(chronicles, monkeypatch, capsys):
    from rpg_chronicler import chronicle_pdf
    written = {}
    monkeypatch.setattr(chronicle_pdf, "write_markdown_pdf", lambda text, path, line: written.update(path=path))
    chronicles.llm.response = "Wpis."
    assert cli.main(["diary", "Warhammer", "fen"]) == 0
    md = diary.markdown_path("Warhammer", "Fen Wanderer")
    assert os.path.exists(md) and written["path"] == diary.pdf_path("Warhammer", "Fen Wanderer")
    assert "[SUKCES] Dziennik postaci Fen Wanderer" in capsys.readouterr().out
