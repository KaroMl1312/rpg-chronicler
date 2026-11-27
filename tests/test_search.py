from rpg_chronicler import cli
from rpg_chronicler.web.text import highlight_markup
from rpg_chronicler.search import KIND_CHRONICLE, KIND_TRANSCRIPT, search, summary_line
from rpg_chronicler.session import list_sessions
from rpg_chronicler.textmatch import contains_name, variants
from rpg_chronicler.transcript import Segment, Transcript, save_speaker_mapping

CHRONICLE = """📜 Kronika Sesji [Warhammer]: Noc Nietoperzy

**🌄 Świt i Wybór Drogi**
- **Wskazówka:** Kapłanka kazała Wam odnaleźć **Ojca Romulusa**.
- Kupiec z Altdorfu sprzedał Wam konia.
"""


def _transcript(*texts, speaker="SPEAKER_00"):
    return Transcript(segments=[Segment(i * 10.0, i * 10.0 + 8, t, speaker) for i, t in enumerate(texts)]).to_txt()


def test_variants_cover_inflection_and_mobile_e():
    assert contains_name("Rozmawialiście z Ulrichem", "Ulrich")
    assert contains_name("u kupca", "kupiec") and contains_name("dla Marka", "Marek")
    assert not contains_name("Fen", "Fen Wanderer")   # wszystkie słowa nazwy muszą wystąpić
    assert variants("Altdorf") == ("altdo",)


def test_search_orders_by_session_date_and_marks_kinds(workspace):
    workspace.add_transcript("Warhammer_261105", _transcript("Ojciec Romulus czeka", "nic"))
    workspace.add_transcript("Warhammer_260924", _transcript("Szukamy Romulusa w Dolinie"))
    workspace.add_transcript("Fallout_260930", _transcript("Romulus z Megatonu"))
    (workspace.dirs["summary"] / "Warhammer_261105_podsumowanie.txt").write_text(CHRONICLE, encoding="utf-8")
    save_speaker_mapping(str(workspace.dirs["txt"] / "Warhammer_260924.txt"), {"SPEAKER_00": "MG"})

    hits = search(list_sessions(), "romulus", campaign="Warhammer")
    assert [(h.session, h.kind) for h in hits] == [
        ("Warhammer_260924", KIND_TRANSCRIPT), ("Warhammer_261105", KIND_CHRONICLE),
        ("Warhammer_261105", KIND_TRANSCRIPT)]
    first, chronicle_hit = hits[0], hits[1]
    assert first.speaker == "MG" and first.start == 0.0 and "Romulusa" in first.text
    assert chronicle_hit.heading == "🌄 Świt i Wybór Drogi"
    assert chronicle_hit.text == "- Wskazówka: Kapłanka kazała Wam odnaleźć Ojca Romulusa."
    assert summary_line(hits) == "3 trafienia w 2 sesjach, pierwsze: Warhammer_260924"
    assert len(search(list_sessions(), "romulus")) == 4   # bez filtra także Fallout


def test_multiword_query_matches_within_few_utterances(workspace):
    workspace.add_transcript("W_1", _transcript("Kapłanka powiedziała", "że Mor nas strzeże", "a", "b", "c", "Mor"))
    hits = search(list_sessions(), "kapłanka Mor", chronicles=False)
    assert len(hits) == 1 and hits[0].start == 0.0 and hits[0].end == 18.0


def test_search_command(workspace, capsys):
    workspace.add_transcript("Warhammer_260924", _transcript("Szukamy Romulusa"))
    assert cli.main(["search", "Romulus"]) == 0
    out = capsys.readouterr().out
    assert "1 trafienie w 1 sesji" in out and "[0:00:00 · SPEAKER_00] Szukamy Romulusa" in out


def test_highlight_markup_escapes_and_bolds_inflected_words():
    assert highlight_markup("Ojca Romulusa & <spółka>", "romulus") == \
        "Ojca <b>Romulusa</b> &amp; &lt;spółka&gt;"
