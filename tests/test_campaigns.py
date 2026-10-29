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
