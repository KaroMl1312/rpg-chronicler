import os
import tempfile
from unittest import mock

from rpg_chronicler import campaigns
from rpg_chronicler.campaigns import Campaign, campaign_for, load_campaigns

TOML = """
[Warhammer]
system = "Warhammer Fantasy Roleplay"
kontekst = "Imperium, Altdorf."

[Zakon]
"""


def test_load_campaigns_from_toml():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "kampanie.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TOML)
        loaded = load_campaigns(path)
    assert loaded["Warhammer"] == Campaign("Warhammer", "Warhammer Fantasy Roleplay", "Imperium, Altdorf.")
    assert loaded["Zakon"] == Campaign("Zakon", "Zakon")  # bez "system" -> nazwa sekcji


def test_campaign_for_uses_config_then_falls_back_to_filename():
    configured = {"Warhammer": Campaign("Warhammer", "Warhammer Fantasy Roleplay")}
    with mock.patch.object(campaigns, "load_campaigns", lambda: configured):
        assert campaign_for("Warhammer_261015").system == "Warhammer Fantasy Roleplay"
        assert campaign_for("call-of-cthulhu_01").system == "Call Of Cthulhu"
        assert campaign_for("sesja").system == "RPG"


def test_missing_file_means_no_campaigns():
    assert load_campaigns("/nie/ma/takiego/pliku.toml") == {}


FULL = Campaign(
    key="Warhammer", system="Warhammer Fantasy Roleplay",
    context="Imperium, rok 2512.\nZaraza w Ubersreiku. Cytat: 'cisza'",
    player_characters={"Fen": "Ania", "Sir Amos": ""},
    glossary={"npc": ("Eustachy", "Matka Helga"), "miejsca": ("Altdorf",), "inne": ('Zakon "Mora"',)},
)


def test_save_and_load_full_campaign_roundtrip(tmp_path):
    path = str(tmp_path / "kampanie.toml")
    campaigns.save_campaigns({"Warhammer": FULL, "Zakon": Campaign("Zakon", "Zakon")}, path)
    loaded = load_campaigns(path)
    assert loaded["Warhammer"] == FULL
    assert loaded["Zakon"] == Campaign("Zakon", "Zakon")
    assert "'''" in open(path, encoding="utf-8").read()  # wielowierszowy opis czytelnie, nie jako \n


def test_update_campaign_and_cache_refresh(tmp_path):
    path = str(tmp_path / "kampanie.toml")
    campaigns.save_campaigns({"Zakon": Campaign("Zakon", "Zakon")}, path)
    assert load_campaigns(path)["Zakon"].player_characters == {}
    campaigns.update_campaign(Campaign("Zakon", "Zakon", player_characters={"Brat Jan": ""}), path)
    assert load_campaigns(path)["Zakon"].player_characters == {"Brat Jan": ""}


def test_player_characters_as_list_and_names_deduplicated(tmp_path):
    path = tmp_path / "kampanie.toml"
    path.write_text('[Fallout]\npostacie_graczy = ["Kate", "Way"]\nnpc = ["Johnny", "johnny", " "]\n',
                    encoding="utf-8")
    fallout = load_campaigns(str(path))["Fallout"]
    assert fallout.player_characters == {"Kate": "", "Way": ""}
    assert fallout.names("npc") == ("Johnny",)
    assert fallout.all_names() == ["Kate", "Way", "Johnny"]


def test_prompt_info():
    info = FULL.prompt_info()
    assert "Zaraza w Ubersreiku" in info
    assert "- Fen (gracz: Ania)" in info and "- Sir Amos\n" in info
    assert "Postacie niezależne (NPC): Eustachy, Matka Helga" in info
    assert Campaign("X", "X").prompt_info() == ""


def test_session_date_formats():
    import datetime
    assert campaigns.session_date("Warhammer_261015") == datetime.date(2026, 10, 15)
    assert campaigns.session_date("Fallout_16_09_2026") == datetime.date(2026, 9, 16)
    assert campaigns.session_date("Zakon_9_9_2026") == datetime.date(2026, 9, 9)
    assert campaigns.session_date("Sesja") is None
    assert campaigns.session_date("Zakon_261399") is None  # 99. dzień miesiąca
