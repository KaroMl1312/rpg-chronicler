import io
import json
import urllib.error

import pytest

from rpg_chronicler import chronicle, cli, discord, settings
from rpg_chronicler.chronicle_pdf import chronicle_html, strip_emoji
from rpg_chronicler.session import list_sessions

WEBHOOK = "https://discord.com/api/webhooks/123/abc-DEF_1"
CHRONICLE = "📜 **Kronika Sesji [Warhammer]: Lekarstwo**\n\n---\n\n### 🌿 **Mobilizacja**\n\n* **Sojusz:** Fen i Sir Amos.\n"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent_requests(monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        return FakeResponse(json.dumps({"id": "999"}).encode())

    monkeypatch.setattr(discord.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(discord.time, "sleep", lambda _s: None)
    return requests


@pytest.fixture
def chronicle_session(workspace, tmp_path, monkeypatch):
    monkeypatch.setenv(settings.ENV_VAR, str(tmp_path / "ustawienia.toml"))
    workspace.add_transcript("Warhammer_261015", "[0.00s -> 1.00s] x\n")
    (workspace.dirs["summary"] / "Warhammer_261015_podsumowanie.txt").write_text(CHRONICLE, encoding="utf-8")
    return list_sessions()[0]


def test_title_date_and_paths(chronicle_session):
    assert chronicle.chronicle_title(CHRONICLE) == "📜 Kronika Sesji [Warhammer]: Lekarstwo"
    assert chronicle.session_date_text(chronicle_session) == "15 października 2026"
    assert chronicle.pdf_path(chronicle_session).endswith("Warhammer_261015_kronika.pdf")


def test_pdf_html_without_emoji_and_duplicate_title(chronicle_session):
    document = chronicle_html(CHRONICLE, chronicle_session)
    assert "📜" not in document and "🌿" not in document
    assert document.count("Kronika Sesji [Warhammer]: Lekarstwo") == 2  # <title> i nagłówek, bez powtórzenia w treści
    assert "<h3><strong>Mobilizacja</strong></h3>" in document and "<hr" not in document
    assert "Sesja z 15 października 2026" in document
    assert strip_emoji("⚔️ Bitwa 🧙🏻‍♂️ maga") == " Bitwa maga"


def test_send_builds_multipart_with_pdf(sent_requests, tmp_path):
    pdf = tmp_path / "kronika.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    message = discord.build_message("Tytuł", "Zapowiedź", "Warhammer", "kronika.pdf")
    assert discord.send(WEBHOOK, message, str(pdf)) == "999"
    request = sent_requests[0]
    assert request.full_url == WEBHOOK + "?wait=true"
    assert request.headers["User-agent"].startswith("DiscordBot")
    body = request.data
    assert b'name="payload_json"' in body and b'filename="kronika.pdf"' in body and b"%PDF-1.7 test" in body
    payload = json.loads(body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
    assert payload["embeds"][0]["title"] == "Tytuł" and payload["allowed_mentions"] == {"parse": []}


def test_send_errors(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append(1)
        code = 429 if len(calls) == 1 else 404
        raise urllib.error.HTTPError(request.full_url, code, "x", {"Retry-After": "1"},
                                     io.BytesIO(b'{"message": "Unknown Webhook"}'))

    monkeypatch.setattr(discord.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(discord.time, "sleep", lambda _s: None)
    with pytest.raises(discord.DiscordError, match="Unknown Webhook"):
        discord.send(WEBHOOK, discord.build_message("T", "Z", "S", None))
    assert len(calls) == 2  # 429 -> ponowienie, 404 -> błąd bez ponawiania
    with pytest.raises(discord.DiscordError, match="Niepoprawny adres"):
        discord.send("https://example.com/hook", {})


def test_cli_discord_full_flow(chronicle_session, workspace, sent_requests, monkeypatch, capsys):
    pytest.importorskip("weasyprint")  # PDF w załączniku; w CI instalowany osobno
    monkeypatch.setattr("rpg_chronicler.llm.get_client", lambda provider: workspace.llm)
    workspace.llm.response = "„Wasza drużyna warzy lek 🌿.”"

    assert cli.main(["discord", "Warhammer_261015"]) == 1  # brak webhooka
    assert "nie ma ustawionego webhooka" in capsys.readouterr().err
    assert chronicle.read_teaser(chronicle_session) == "Wasza drużyna warzy lek 🌿."
    assert chronicle.pdf_is_current(chronicle_session)  # PDF przygotowany mimo braku webhooka

    chronicle.set_webhook("Warhammer", WEBHOOK)
    assert cli.main(["discord", "Warhammer_261015"]) == 0
    payload = json.loads(sent_requests[0].data.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
    assert payload["embeds"][0]["description"] == "Wasza drużyna warzy lek 🌿."
    assert payload["embeds"][0]["footer"]["text"] == "Warhammer · 15 października 2026"
    assert chronicle.load_sent(chronicle_session)["wiadomosc"] == "999"
    assert len(workspace.llm.prompts) == 1  # zapowiedź zapamiętana, bez ponownego pytania AI

    assert cli.main(["discord", "Warhammer_261015"]) == 1  # już wysłano
    assert "--force" in capsys.readouterr().err
    assert cli.main(["discord", "Warhammer_261015", "--force"]) == 0 and len(sent_requests) == 2


def test_discord_state_mark_and_older_version(chronicle_session, capsys):
    import os
    import time

    assert chronicle.discord_state(chronicle_session) == chronicle.NOT_SENT
    assert chronicle.discord_label(chronicle_session) == ""
    assert cli.main(["discord", "Warhammer_261015", "--oznacz"]) == 0          # bez webhooka i bez wysyłania
    assert chronicle.discord_state(chronicle_session) == chronicle.SENT
    assert chronicle.load_sent(chronicle_session)["recznie"] is True
    assert "(oznaczone ręcznie)" in chronicle.discord_label(chronicle_session)
    assert cli.main(["status"]) == 0
    assert "DISCORD" in capsys.readouterr().out

    later = time.time() + 120                                                  # poprawka kroniki po wysłaniu
    os.utime(chronicle_session.summary_path, (later, later))
    assert chronicle.discord_state(chronicle_session) == chronicle.SENT_OLDER
    assert chronicle.discord_label(chronicle_session).startswith("na Discordzie starsza wersja")
    cli.main(["status"])
    assert "starsza" in capsys.readouterr().out

    assert cli.main(["discord", "Warhammer_261015", "--odznacz"]) == 0
    assert chronicle.discord_state(chronicle_session) == chronicle.NOT_SENT
    assert cli.main(["discord", "Warhammer_261015", "--odznacz"]) == 0          # drugi raz - bez błędu
