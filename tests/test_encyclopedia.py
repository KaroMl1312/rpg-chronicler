import json

import pytest

from rpg_chronicler import campaigns, encyclopedia, memory
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.session import list_sessions

CAMPAIGN = Campaign("Warhammer", "WFRP", "Pogranicze.", player_characters={"Fen Wanderer": "Ania"},
                    glossary={"npc": ["Ojciec Romulus"], "miejsca": ["Altdorf"]})
AI_RESPONSE = json.dumps({"hasla": [
    {"nazwa": "Ojciec Romulus", "kategoria": "npc", "opis": "Zna tajemnicę klątwy.", "sesje": ["Warhammer_261015"]},
    {"nazwa": "fen wanderer", "kategoria": "npc", "opis": "Gnom, mag.", "sesje": ["Warhammer_260924", "Zmyślona_1"]},
    {"nazwa": "Sygnet", "kategoria": "przedmioty", "opis": "Klucz do klątwy.", "sesje": []},
    {"nazwa": "", "kategoria": "npc", "opis": "pusty - pomijany"},
]})


@pytest.fixture
def chronicles(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Warhammer": CAMPAIGN})
    texts = {"Warhammer_260924": "# Kronika Sesji [Warhammer]: Pierwsza\n\nFen leczy chorych w Altdorfie.",
             "Warhammer_261015": "# Kronika Sesji: Druga\n\nKapłanka wskazała Ojca Romulusa. Sygnet świeci."}
    for name, text in texts.items():
        workspace.add_transcript(name, "[0.00s -> 1.00s] x\n")
        (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(text, encoding="utf-8")
    return workspace


def test_build_merges_ai_entries_and_counts_sessions(chronicles):
    chronicles.llm.response = AI_RESPONSE
    memory.save_state("Warhammer", "## Drużyna\n- Fen ranny", "Warhammer_261015")
    text = encyclopedia.build(CAMPAIGN, list_sessions(), chronicles.llm)

    assert text.startswith("# Encyklopedia kampanii Warhammer\n\n*WFRP · 2 sesji")
    assert "### 1. 24.09.2026 — Pierwsza" in text and "### 2. 15.10.2026 — Druga" in text
    assert "## Stan kampanii (po sesji 15.10.2026)\n\n### Drużyna" in text
    # słownik decyduje o kategorii i pisowni; AI dodaje opisy, sesje i nowe hasła
    assert "## Postacie graczy\n\n**Fen Wanderer** — Gnom, mag. *Sesje: 24.09.2026.*" in text
    assert "**Ojciec Romulus** — Zna tajemnicę klątwy. *Sesje: 15.10.2026.*" in text
    assert "**Altdorf** *Sesje: 24.09.2026.*" in text            # dopasowanie z odmianą („w Altdorfie”)
    assert "**Sygnet** — Klucz do klątwy. *Sesje: 15.10.2026.*" in text
    assert "Zmyślona" not in text and "pusty" not in text
    assert "<kronika" in chronicles.llm.prompts[0] and "Ojciec Romulus" in chronicles.llm.prompts[0]

    encyclopedia.build(CAMPAIGN, list_sessions(), chronicles.llm)
    assert len(chronicles.llm.prompts) == 1   # odpowiedź AI z pamięci podręcznej


def test_build_without_ai_lists_glossary_only(chronicles):
    text = encyclopedia.build(CAMPAIGN, list_sessions(), None)
    assert "**Altdorf** *Sesje: 24.09.2026.*" in text
    # bez AI tylko pełna nazwa w regularnej odmianie - „Fen” ani „Ojca” (nieregularne) nie wystarczą
    assert "**Fen Wanderer** *Nie pojawia się w kronikach.*" in text
    assert "**Ojciec Romulus** *Nie pojawia się w kronikach.*" in text
    assert chronicles.llm.prompts == []


def test_no_chronicles_is_an_error(workspace):
    with pytest.raises(encyclopedia.EncyclopediaError):
        encyclopedia.build(CAMPAIGN, list_sessions(), None)


def test_markdown_document_html_puts_title_in_header():
    from rpg_chronicler.chronicle_pdf import markdown_document_html
    page = markdown_document_html("# Encyklopedia 📜\n\n*WFRP · 2 sesji*\n\n## Oś czasu\n\nTekst", "WFRP")
    assert "<h1>Encyklopedia</h1>" in page and '<div class="date">WFRP · 2 sesji</div>' in page
    assert "<h2>Oś czasu</h2>" in page and "📜" not in page
