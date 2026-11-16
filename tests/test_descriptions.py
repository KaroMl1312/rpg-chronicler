"""Opisy i zdjęcia haseł kampanii (postacie, BN-i, miejsca…): kampanie.toml, obrazy/, encyklopedia, `describe`."""
import json

import pytest

from rpg_chronicler import campaigns, cli, config, encyclopedia
from rpg_chronicler.campaigns import Campaign, load_campaigns

CAMPAIGN = Campaign("Warhammer", "Warhammer Fantasy", player_characters={"Fen Wanderer": "Ania"},
                    glossary={"npc": ("Ojciec Romulus", "Hans"), "miejsca": ("Ubersreik",)},
                    descriptions={"Ojciec Romulus": "Kapłan Morra z Ubersreiku.\nPomógł drużynie."})


def test_descriptions_roundtrip_and_pruning(tmp_path):
    path = str(tmp_path / "kampanie.toml")
    campaign = CAMPAIGN.with_description("fen wanderer", "Tropicielka z Reiklandu.").with_description("Ktoś", "x")
    campaigns.save_campaigns({"Warhammer": campaign}, path)
    content = open(path, encoding="utf-8").read()
    assert "[Warhammer.opisy]" in content and "Ktoś" not in content       # opis nazwy spoza słownika odpada
    assert content.index("[Warhammer.opisy]") < content.index("[Warhammer.postacie_graczy]")
    loaded = load_campaigns(path)["Warhammer"]
    assert loaded.description("ojciec romulus") == "Kapłan Morra z Ubersreiku.\nPomógł drużynie."
    assert loaded.description("Fen Wanderer") == "Tropicielka z Reiklandu."
    assert loaded.player_characters == {"Fen Wanderer": "Ania"} and loaded.description("Hans") == ""
    assert loaded.with_description("Ojciec Romulus", "  ").description("Ojciec Romulus") == ""   # pusty = usuń


def test_images(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TXT_DIR", str(tmp_path / "txt"))
    photo = tmp_path / "Romulus.JPG"
    photo.write_bytes(b"jpeg")
    assert campaigns.image_path("Warhammer", "Ojciec Romulus") is None
    saved = campaigns.set_image("Warhammer", "Ojciec Romulus", str(photo))
    assert saved == str(tmp_path / "txt" / "obrazy" / "Warhammer" / "ojciec_romulus.jpg")
    png = tmp_path / "nowe.png"
    png.write_bytes(b"png")
    campaigns.set_image("Warhammer", "ojciec romulus", str(png))     # zastępuje (inne rozszerzenie)
    assert campaigns.image_path("Warhammer", "Ojciec Romulus").endswith("ojciec_romulus.png")
    assert sorted(p.name for p in (tmp_path / "txt" / "obrazy" / "Warhammer").iterdir()) == ["ojciec_romulus.png"]
    with pytest.raises(ValueError):
        campaigns.set_image("Warhammer", "Hans", str(tmp_path / "plik.gif"))
    campaigns.remove_image("Warhammer", "Ojciec Romulus")
    assert campaigns.image_path("Warhammer", "Ojciec Romulus") is None


def test_fill_descriptions_keeps_existing():
    from_ai = [encyclopedia.Entry("ojciec romulus", "npc", "Opis od AI."), encyclopedia.Entry("Hans", "npc", "Kupiec."),
               encyclopedia.Entry("Nowy BN", "npc", "Spoza słownika.")]
    updated, filled = encyclopedia.fill_descriptions(CAMPAIGN, from_ai)
    assert filled == ["Hans"]
    assert updated.description("Ojciec Romulus").startswith("Kapłan Morra") and updated.description("Hans") == "Kupiec."
    assert updated.description("Nowy BN") == ""
    entries = {e.name: e for e in encyclopedia.merge(encyclopedia.glossary_entries(updated), from_ai)}
    assert entries["Ojciec Romulus"].description.startswith("Kapłan Morra")    # opis z kampanii wygrywa z AI


def test_describe_command(workspace, monkeypatch, capsys):
    saved = {}
    monkeypatch.setattr(campaigns, "load_campaigns", lambda path=None: {"Warhammer": saved.get("c", CAMPAIGN)})
    monkeypatch.setattr(campaigns, "update_campaign", lambda c, path=None: saved.update(c=c))
    workspace.add_transcript("Warhammer_261105", "[0.00s -> 1.00s] Witajcie.\n")
    (workspace.dirs["summary"] / "Warhammer_261105_podsumowanie.txt").write_text("Hans sprzedał linę.", "utf-8")
    workspace.llm.response = json.dumps({"hasla": [{"nazwa": "Hans", "kategoria": "npc", "opis": "Kupiec z mostu.",
                                                    "sesje": ["Warhammer_261105"]}]})
    assert cli.main(["describe", "Warhammer"]) == 0
    out = capsys.readouterr().out
    assert "dodano 1 (Hans)" in out and "Bez opisu (2): Fen Wanderer, Ubersreik" in out
    assert saved["c"].description("Hans") == "Kupiec z mostu."
    assert cli.main(["describe", "Warhammer"]) == 0                     # odpowiedź z cache, nic nowego
    assert len(workspace.llm.prompts) == 1 and "brak nowych opisów" in capsys.readouterr().out
