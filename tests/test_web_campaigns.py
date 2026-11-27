"""Nowe okno, etap 3: zakładka Kampanie (web/campaign_api.py) i zamykanie okna."""
import base64
import threading

import pytest

from rpg_chronicler import campaigns, config
from rpg_chronicler.campaign_tools import ask, glossary, images, memory
from rpg_chronicler.campaign_tools.ask import Answer
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.web import campaign_api
from rpg_chronicler.web.__main__ import closing_handler
from rpg_chronicler.web.server import App, start_server
from test_web import _request

load_campaigns = campaigns.load_campaigns   # fixture workspace podmienia ją na pustą


@pytest.fixture
def zakon(workspace, monkeypatch):
    monkeypatch.setattr(campaigns, "load_campaigns", load_campaigns)
    monkeypatch.setattr(config, "TXT_DIR", str(workspace.dirs["txt"]))
    campaigns.update_campaign(Campaign("Inna", "Inny system"))
    campaigns.update_campaign(Campaign("Zakon", "Zakon", player_characters={"Fen": ""},
                                       glossary={"npc": ("Hans", "Ojciec Romulus")},
                                       descriptions={"Hans": "Karczmarz."}))
    workspace.add_transcript("Nowa_261015", "[0.00s -> 1.00s] Tekst.\n")
    return workspace


def load():
    return load_campaigns()["Zakon"]


def test_list_create_and_detail(zakon):
    data = campaign_api.campaign_list()
    assert [c["key"] for c in data["campaigns"]] == ["Inna", "Zakon"] and data["missing"] == ["Nowa"]
    for bad in ("", "../zla", "a_b", "a/b", "a.b"):
        with pytest.raises(ValueError):
            campaign_api.create(bad)
    detail = campaign_api.detail("Zakon")
    assert detail["described"] == 1 and detail["names_count"] == 3 and detail["has_chronicles"] is False
    assert campaign_api.detail("Nowa")["system"] == "Nowa"          # prefiks nagrań bez wpisu w pliku
    with pytest.raises(ValueError):
        campaign_api.detail("../../etc")


def test_changes_are_saved_and_keep_other_campaigns(zakon):
    for what, body in (("system", {"value": " Nowy "}), ("context", {"value": "Dolina"}),
                       ("add_character", {"value": "Amos = Ania"}), ("set_player", {"name": "Fen", "value": "Ola"}),
                       ("add_names", {"category": "miejsca", "value": "Altdorf, Dolina,"}),
                       ("remove_name", {"category": "npc", "name": "Ojciec Romulus"}),
                       ("description", {"name": "fen", "value": "Tropicielka"}),
                       ("voice_threshold", {"value": "0,65"})):
        campaign_api.change("Zakon", what, body)
    c = load()
    assert (c.system, c.context, c.player_characters) == ("Nowy", "Dolina", {"Fen": "Ola", "Amos": "Ania"})
    assert c.names("miejsca") == ("Altdorf", "Dolina") and c.names("npc") == ("Hans",)
    assert c.description("Fen") == "Tropicielka" and "Inna" in load_campaigns()
    assert c.voice_threshold == 0.65 and campaign_api.detail("Zakon")["voice_threshold"] == "0.65"
    campaign_api.change("Zakon", "voice_threshold", {"value": ""})
    assert load().voice_threshold is None
    for what, body in (("system", {"value": " "}), ("add_names", {"category": "zla", "value": "x"}),
                       ("description", {"name": "Nikt", "value": "x"}), ("usun_wszystko", {}),
                       ("voice_threshold", {"value": "1,5"})):
        with pytest.raises(ValueError):
            campaign_api.change("Zakon", what, body)


def test_broken_campaign_file_is_not_overwritten(zakon):
    path = campaigns.campaigns_file()
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n[zepsute\n")
    before = open(path, encoding="utf-8").read()
    with pytest.raises(ValueError):
        campaign_api.create("Swieza")
    with pytest.raises(ValueError):
        campaign_api.change("Nowa", "system", {"value": "X"})
    assert open(path, encoding="utf-8").read() == before


def test_concurrent_changes_do_not_get_lost(zakon):
    threads = [threading.Thread(target=campaign_api.change,
                                args=("Zakon", "add_names", {"category": "inne", "value": f"Nazwa {i}"}))
               for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(load().names("inne")) == 12


def test_resolve_proposals_only_what_was_shown(zakon):
    glossary.save_proposals("Zakon", {"npc": ["Kapłanka", "Śmieć"], "opis": "Dolina."})
    shown = {"npc": ["Kapłanka", "Śmieć"], "opis": "Dolina."}
    glossary.add_proposals(load(), {"npc": ["Doszła później"]})     # zadanie w tle w międzyczasie
    result = campaign_api.resolve_proposals("Zakon", shown, {"npc": ["Kapłanka", "Wymyślona"], "opis": "podmieniony"})
    assert result == {"added": 2} and load().context == "Dolina."
    assert load().names("npc") == ("Hans", "Ojciec Romulus", "Kapłanka")
    assert glossary.pending_for(load())["npc"] == ["Doszła później"]


def test_memory_refuses_text_of_replaced_proposal(zakon):
    memory.save_proposal("Zakon", memory.State("Stan 1", "Zakon_261001"))
    memory.save_proposal("Zakon", memory.State("Stan 2", "Zakon_261008"))
    with pytest.raises(ValueError):
        campaign_api.memory_action("Zakon", "accept", "Stan 1 poprawiony", "Zakon_261001")
    assert memory.load_proposal("Zakon").text == "Stan 2" and memory.load_state("Zakon") is None
    campaign_api.memory_action("Zakon", "accept", "Stan 2 poprawiony", "Zakon_261008")
    assert memory.load_state("Zakon") == memory.State("Stan 2 poprawiony", "Zakon_261008")
    campaign_api.memory_action("Zakon", "save", "Ręcznie", "Zakon_261008")
    assert memory.load_state("Zakon") == memory.State("Ręcznie", "Zakon_261008")


def test_forget_answer_by_content(zakon):
    ask._save_history("Zakon", [Answer("Nowe?", "B", [], "2"), Answer("Stare?", "A <img src=x>", [], "1")])
    assert "<img" not in campaign_api.detail("Zakon")["history"][1]["html"]
    campaign_api.forget_answer("Zakon", "Stare?", "1")
    assert [a.question for a in ask.load_history("Zakon")] == ["Nowe?"]


def test_entry_images(zakon):
    data = base64.b64encode(b"png").decode()
    campaign_api.upload_image("Zakon", "hans", "a.PNG", data)
    assert campaign_api.entry("Zakon", "Hans")["image"]
    for name, filename, content in (("Hans", "a.svg", data), ("Hans", "a.png", "nie base64!"), ("../x", "a.png", data),
                                    ("Hans", "a.png", "")):
        with pytest.raises(ValueError):
            campaign_api.upload_image("Zakon", name, filename, content)
    folder = images.candidates_dir("Zakon")
    folder.mkdir(parents=True)
    (folder / "ojciec_romulus__20261123.jpg").write_bytes(b"jpg")
    assert campaign_api.entry("Zakon", "Ojciec Romulus")["proposal"]
    campaign_api.image_action("Zakon", "Ojciec Romulus", "keep")
    assert campaigns.image_path("Zakon", "Ojciec Romulus").endswith(".jpg")
    campaign_api.image_action("Zakon", "Hans", "remove")
    assert campaign_api.entry("Zakon", "Hans")["image"] == ""

    app = App()
    server, url = start_server(app)
    base = url.split("#")[0].rstrip("/")
    try:
        address = f"{base}/api/image?key=Zakon&name=Ojciec%20Romulus"
        assert _request(address)[0] == 403
        assert _request(f"{address}&t={app.token}") == (200, b"jpg")
        assert _request(f"{base}/api/image?key=Zakon&name=Hans&t={app.token}")[0] == 404
        status, _body = _request(f"{base}/api/campaign", app.token, {"key": "Zakon", "what": "system", "value": "Z API"})
        assert status == 200 and load().system == "Z API"
    finally:
        server.shutdown()


class FakeWindow:
    def __init__(self, answer):
        self.answer, self.destroyed, self.asked = answer, threading.Event(), threading.Event()

    def evaluate_js(self, code, callback):
        assert code == "confirmClose()"
        self.asked.set()
        if isinstance(self.answer, Exception):
            raise self.answer
        callback(self.answer)

    def destroy(self):
        self.destroyed.set()


@pytest.mark.parametrize("answer, closes", [(True, True), (False, False), (RuntimeError("strona padła"), True)])
def test_pywebview_close_waits_for_page(answer, closes):
    window = FakeWindow(answer)
    on_closing = closing_handler(window)
    assert on_closing() is False            # najpierw pytamy stronę
    assert window.asked.wait(5)
    assert window.destroyed.wait(5 if closes else 0.3) is closes
    if closes:
        assert on_closing() is None         # zamknięcie wywołane przez destroy() już przechodzi
    else:
        window.asked.clear()
        assert on_closing() is False and window.asked.wait(5)   # można spróbować ponownie
