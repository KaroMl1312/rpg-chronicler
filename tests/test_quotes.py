import json
import os
import time

import pytest

from rpg_chronicler import after_chronicle, chronicle, cli, discord, llm
from rpg_chronicler.session import list_sessions

LEGACY = "[0.00s -> 2.00s]  Czy ten koń zje mnie, skoro nie ma szczęki?\n"
RESPONSE = json.dumps({"cytaty": [
    {"kto": "Sir Amos", "cytat": "„Czy ten koń będzie chciał mnie zjeść, skoro nie ma szczęki?”"},
    {"kto": "MG", "cytat": "Brakuje mu połowy głowy."},
    {"kto": "Fen", "cytat": ""},
]})


@pytest.fixture
def session(workspace):
    workspace.add_transcript("Warhammer_261105", LEGACY)
    (workspace.dirs["summary"] / "Warhammer_261105_podsumowanie.txt").write_text("# Kronika\n\nStodoła.", "utf-8")
    return list_sessions()[0]


def test_quotes_file_roundtrip_and_tolerant_parsing():
    quotes = [("Tak?", "Fen"), ("No i tyle.", "")]
    assert chronicle.format_quotes(quotes) == "„Tak?” — Fen\n„No i tyle.”\n"
    assert chronicle.parse_quotes("„Tak?” — Fen\n- \"Hej\" - MG\nzwykła linia\n„No i tyle.”\n") == \
        [("Tak?", "Fen"), ("Hej", "MG"), ("No i tyle.", "")]


def test_write_quotes_from_transcript(workspace, session):
    workspace.llm.response = RESPONSE
    quotes = after_chronicle.write_quotes(workspace.llm, session, "# Kronika\n\nStodoła.")
    assert quotes == [("Czy ten koń będzie chciał mnie zjeść, skoro nie ma szczęki?", "Sir Amos"),
                      ("Brakuje mu połowy głowy.", "MG")]
    assert chronicle.read_quotes(session) == quotes
    prompt = workspace.llm.prompts[0]
    assert prompt.startswith('<kronika sesja="Warhammer_261105">') and "<transkrypcja>" in prompt
    assert "skoro nie ma szczęki" in prompt


def test_quotes_prefer_candidates_from_events(workspace, session):
    (workspace.dirs["summary"] / "Warhammer_261105_wydarzenia.md").write_text(
        "## Część 1 z 2\n\n- Stodoła\n\n### Cytaty\n\n- Sir Amos: „Kandydat pierwszy”\n\n"
        "## Część 2 z 2\n\n- Walka\n\n### Cytaty\n- MG: „Kandydat drugi”\n", encoding="utf-8")
    workspace.llm.response = RESPONSE
    after_chronicle.write_quotes(workspace.llm, session, "K")
    prompt = workspace.llm.prompts[0]
    assert "Kandydat pierwszy" in prompt and "Kandydat drugi" in prompt and "<transkrypcja>" not in prompt
    assert "- Walka" not in prompt


def test_quotes_command_and_bad_response(workspace, session, monkeypatch, capsys):
    monkeypatch.setattr(llm, "get_client", lambda provider: workspace.llm)
    workspace.llm.response = "nie wiem"
    assert cli.main(["quotes"]) == 0
    assert "nie zawiera obiektu JSON" in capsys.readouterr().out
    assert not os.path.exists(chronicle.quotes_path(session))
    workspace.llm.response = RESPONSE
    assert cli.main(["quotes"]) == 0 and len(chronicle.read_quotes(session)) == 2
    assert cli.main(["quotes"]) == 0 and "mają już cytaty" in capsys.readouterr().out


def test_quotes_in_pdf_and_pdf_freshness(session):
    from rpg_chronicler.chronicle_pdf import chronicle_html
    chronicle.save_quotes(session, [("Tak? <b>", "Fen")])
    page = chronicle_html("# Kronika\n\nStodoła.", session)
    assert '<h2>Cytaty sesji</h2><blockquote><p>„Tak? &lt;b&gt;”</p><div class="who">— Fen</div>' in page

    with open(chronicle.pdf_path(session), "w") as f:
        f.write("pdf")
    assert chronicle.pdf_is_current(session)
    later = time.time() + 5
    os.utime(chronicle.quotes_path(session), (later, later))
    assert not chronicle.pdf_is_current(session)   # nowsze cytaty → PDF do odświeżenia


def test_discord_description_with_quotes_respects_limit():
    quotes = [("Tak?", "Fen"), ("Hej", "")]
    assert discord.description_with_quotes("Zapowiedź", quotes) == \
        "Zapowiedź\n\n**Cytaty sesji**\n> „Tak?” — *Fen*\n> „Hej”"
    assert discord.description_with_quotes("Zapowiedź", []) == "Zapowiedź"
    long_teaser = "x" * (discord.DESCRIPTION_LIMIT - 30)
    assert discord.description_with_quotes(long_teaser, quotes) == long_teaser   # nie zmieszczą się
    message = discord.build_message("T", "Z", "S", None, quotes)
    assert "Cytaty sesji" in message["embeds"][0]["description"]
