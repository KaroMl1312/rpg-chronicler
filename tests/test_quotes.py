import json
import os
import time

import pytest

from rpg_chronicler import after_chronicle, chronicle, cli, discord, llm
from rpg_chronicler.chronicle import Quote
from rpg_chronicler.session import list_sessions

# Sir Amos mówi 65-72 s (dwa segmenty), MG od 80 s
LEGACY = ("[SPEAKER_00] [5.00s -> 9.00s]  Wchodzimy do stodoły.\n"
          "[SPEAKER_01] [65.00s -> 69.00s]  Czy ten koń zje mnie,\n"
          "[SPEAKER_01] [69.50s -> 72.00s]  skoro nie ma szczęki?\n"
          "[SPEAKER_00] [80.00s -> 83.00s]  Brakuje mu połowy głowy.\n")
RESPONSE = json.dumps({"cytaty": [
    {"czas": "0:01:05", "kto": "Sir Amos", "cytat": "„Czy ten koń będzie chciał mnie zjeść, skoro nie ma szczęki?”"},
    {"czas": "[0:01:20]", "kto": "MG", "cytat": "Brakuje mu połowy głowy."},
    {"czas": "2:00:00", "kto": "Fen", "cytat": "Czas spoza nagrania."},
    {"kto": "Fen", "cytat": ""},
]})


@pytest.fixture
def session(workspace):
    workspace.add_transcript("Warhammer_261105", LEGACY)
    (workspace.dirs["summary"] / "Warhammer_261105_podsumowanie.txt").write_text("# Kronika\n\nStodoła.", "utf-8")
    return list_sessions()[0]


def test_quotes_file_roundtrip_with_times_and_tolerant_parsing():
    quotes = [Quote("Tak?", "Fen", 334.0, 341.5), Quote("No i tyle.", "", 3725.0), Quote("Bez czasu", "MG")]
    text = chronicle.format_quotes(quotes)
    assert text == "[0:05:34–0:05:42] „Tak?” — Fen\n[1:02:05] „No i tyle.”\n„Bez czasu” — MG\n"
    assert chronicle.parse_quotes(text) == [Quote("Tak?", "Fen", 334.0, 342.0), Quote("No i tyle.", "", 3725.0),
                                            Quote("Bez czasu", "MG")]
    assert chronicle.parse_quotes("- [0:01:05-0:01:12] \"Hej\" - MG\nzwykła linia\n„Stare” — Fen\n") == \
        [Quote("Hej", "MG", 65.0, 72.0), Quote("Stare", "Fen")]


def test_timestamped_transcript_lines_and_spans(session):
    transcript = session.load_transcript()
    text = transcript.compact_for_llm({"SPEAKER_01": "Sir Amos"}, timestamps=True)
    assert text.splitlines()[1] == "[0:01:05] Sir Amos: Czy ten koń zje mnie, skoro nie ma szczęki?"
    assert transcript.line_span(65) == (65.0, 72.0)     # cała wypowiedź z dwóch segmentów
    assert transcript.line_span(66) == (65.0, 72.0)     # AI zaokrągliło o sekundę
    assert transcript.line_span(500) is None
    assert "[" not in transcript.compact_for_llm()     # zwykła kronika bez czasów


def test_write_quotes_from_transcript(workspace, session):
    workspace.llm.response = RESPONSE
    quotes = after_chronicle.write_quotes(workspace.llm, session, "# Kronika\n\nStodoła.")
    assert quotes == [Quote("Czy ten koń będzie chciał mnie zjeść, skoro nie ma szczęki?", "Sir Amos", 65.0, 72.0),
                      Quote("Brakuje mu połowy głowy.", "MG", 80.0, 83.0),
                      Quote("Czas spoza nagrania.", "Fen")]   # zły czas od AI - bez odsłuchu
    assert chronicle.read_quotes(session) == quotes
    prompt = workspace.llm.prompts[0]
    assert prompt.startswith('<kronika sesja="Warhammer_261105">') and "<transkrypcja>" in prompt
    assert "[0:01:05] SPEAKER_01: Czy ten koń zje mnie, skoro nie ma szczęki?" in prompt


def test_quote_per_character_plus_best(workspace, session):
    from rpg_chronicler.transcript import save_speaker_mapping
    save_speaker_mapping(session.txt_path, {"SPEAKER_00": "MG", "SPEAKER_01": "Sir Amos", "SPEAKER_02": "fen",
                                            "SPEAKER_03": "Fen", "SPEAKER_04": "SPEAKER_04"})
    workspace.llm.response = json.dumps({"cytaty": [{"kto": "MG", "cytat": f"Cytat {i}"} for i in range(9)]})
    quotes = after_chronicle.write_quotes(workspace.llm, session, "K")
    prompt = workspace.llm.prompts[0]
    assert "każdej postaci graczy z tej sesji: Sir Amos, fen -" in prompt and "2–3 najciekawsze" in prompt
    assert len(quotes) == 5   # 2 postacie + najwyżej 3 dodatkowe
    assert after_chronicle.max_quotes(["A", "B", "C", "D"]) == 7
    assert "Od 3 do 5" in after_chronicle.quotes_count_rule([])


def test_quotes_prefer_timed_candidates_from_events(workspace, session):
    events = workspace.dirs["summary"] / "Warhammer_261105_wydarzenia.md"
    events.write_text("## Część 1 z 2\n\n- Stodoła\n\n### Cytaty\n\n- [0:01:05] Sir Amos: „Kandydat pierwszy”\n\n"
                      "## Część 2 z 2\n\n- Walka\n\n### Cytaty\n- [0:01:20] MG: „Kandydat drugi”\n", encoding="utf-8")
    workspace.llm.response = RESPONSE
    after_chronicle.write_quotes(workspace.llm, session, "K")
    prompt = workspace.llm.prompts[0]
    assert "Kandydat pierwszy" in prompt and "Kandydat drugi" in prompt and "<transkrypcja>" not in prompt
    assert "- Walka" not in prompt

    # starsza lista wydarzeń - cytaty bez czasu, więc AI dostaje transkrypcję z czasami
    events.write_text("### Cytaty\n- Sir Amos: „Bez czasu”\n", encoding="utf-8")
    after_chronicle.write_quotes(workspace.llm, session, "K")
    assert "<transkrypcja>" in workspace.llm.prompts[1] and "Bez czasu" not in workspace.llm.prompts[1]


def test_quotes_command_and_bad_response(workspace, session, monkeypatch, capsys):
    monkeypatch.setattr(llm, "get_client", lambda provider: workspace.llm)
    workspace.llm.response = "nie wiem"
    assert cli.main(["quotes"]) == 0
    assert "nie zawiera obiektu JSON" in capsys.readouterr().out
    assert not os.path.exists(chronicle.quotes_path(session))
    workspace.llm.response = RESPONSE
    assert cli.main(["quotes"]) == 0 and len(chronicle.read_quotes(session)) == 3
    assert cli.main(["quotes"]) == 0 and "mają już cytaty" in capsys.readouterr().out


def test_quotes_in_pdf_and_pdf_freshness(session):
    from rpg_chronicler.chronicle_pdf import chronicle_html
    chronicle.save_quotes(session, [Quote("Tak? <b>", "Fen", 65.0, 72.0)])
    page = chronicle_html("# Kronika\n\nStodoła.", session)
    assert '<h2>Cytaty sesji</h2><blockquote><p>„Tak? &lt;b&gt;”</p><div class="who">— Fen</div>' in page

    with open(chronicle.pdf_path(session), "w", encoding="utf-8") as f:
        f.write("pdf")
    assert chronicle.pdf_is_current(session)
    later = time.time() + 5
    os.utime(chronicle.quotes_path(session), (later, later))
    assert not chronicle.pdf_is_current(session)   # nowsze cytaty → PDF do odświeżenia


def test_discord_description_with_quotes_respects_limit():
    quotes = [Quote("Tak?", "Fen", 5.0), Quote("Hej")]
    assert discord.description_with_quotes("Zapowiedź", quotes) == \
        "Zapowiedź\n\n**Cytaty sesji**\n> „Tak?” — *Fen*\n> „Hej”"
    assert discord.description_with_quotes("Zapowiedź", []) == "Zapowiedź"
    long_teaser = "x" * (discord.DESCRIPTION_LIMIT - 30)
    assert discord.description_with_quotes(long_teaser, quotes) == long_teaser   # nie zmieszczą się
    message = discord.build_message("T", "Z", "S", None, quotes)
    assert "Cytaty sesji" in message["embeds"][0]["description"]
