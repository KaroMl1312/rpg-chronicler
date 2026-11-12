import json

import pytest

from rpg_chronicler import campaigns, cli, glossary
from rpg_chronicler.campaigns import Campaign

CAMPAIGN = Campaign("Warhammer", "WFRP", player_characters={"Fen": ""}, glossary={"miejsca": ("Altdorf",)})


def test_parse_response_tolerates_extra_text_and_bad_fields():
    text = 'Oto słownik:\n```json\n{"npc": ["Eustachy", 5, " "], "miejsca": "zły typ", "opis": " Świat. "}\n```'
    assert glossary.parse_response(text) == {"npc": ["Eustachy"], "opis": "Świat."}
    with pytest.raises(glossary.GlossaryError):
        glossary.parse_response("brak jsona")


def test_new_only_skips_known_names_case_insensitive():
    proposals = {"postacie_graczy": ["fen", "Kate"], "miejsca": ["ALTDORF", "Ubersreik", "Ubersreik"], "opis": "x"}
    assert glossary.new_only(proposals, CAMPAIGN) == {"postacie_graczy": ["Kate"], "miejsca": ["Ubersreik"],
                                                      "opis": "x"}
    with_context = Campaign("W", "W", context="już jest")
    assert "opis" not in glossary.new_only({"opis": "x"}, with_context)


def test_prompt_contains_current_glossary_and_asks_for_description():
    prefix, prompt = glossary.build_prompt(CAMPAIGN, [("Warhammer_261001", "Kronika 1")])
    assert "postacie_graczy: Fen" in prompt and "miejsca: Altdorf" in prompt
    assert '"opis": ""' in prompt and prefix.startswith('<kronika sesja="Warhammer_261001">')
    with_context = Campaign("W", "W", context="Opis")
    assert '"opis"' not in glossary.build_prompt(with_context, [("W_1", "K")])[1]


def test_accept_and_pending_proposals(workspace):
    glossary.add_proposals(CAMPAIGN, {"postacie_graczy": ["Kate"], "npc": ["Eustachy", "Helga"], "opis": "Świat"})
    glossary.add_proposals(CAMPAIGN, {"npc": ["helga", "Johann"]})  # duplikat pomijany
    pending = glossary.load_proposals("Warhammer")
    assert pending == {"postacie_graczy": ["Kate"], "npc": ["Eustachy", "Helga", "Johann"], "opis": "Świat"}
    assert glossary.count_proposals(pending) == 5

    accepted = {"postacie_graczy": ["Kate"], "npc": ["Eustachy"], "opis": "Świat"}
    updated = glossary.accept(CAMPAIGN, accepted)
    assert updated.player_characters == {"Fen": "", "Kate": ""}
    assert updated.names("npc") == ("Eustachy",) and updated.context == "Świat"

    glossary.remove_from_pending("Warhammer", {**accepted, "npc": ["Eustachy", "Helga"]})  # Helga odrzucona
    assert glossary.load_proposals("Warhammer") == {"npc": ["Johann"]}
    glossary.remove_from_pending("Warhammer", {"npc": ["Johann"]})
    assert not glossary.proposals_path("Warhammer").exists()


def test_cli_glossary_uses_all_chronicles_of_campaign(workspace, monkeypatch):
    for name in ("Warhammer_261001", "Warhammer_260918", "Fallout_261014"):
        workspace.add_transcript(name, "[0.00s -> 1.00s] x\n")
        (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(f"KRONIKA {name}", encoding="utf-8")
    monkeypatch.setattr("rpg_chronicler.llm.get_client", lambda provider: workspace.llm)
    workspace.llm.response = json.dumps({"npc": ["Eustachy"]})

    assert cli.main(["glossary", "Warhammer"]) == 0
    prompt = workspace.llm.prompts[0]
    assert prompt.index("KRONIKA Warhammer_260918") < prompt.index("KRONIKA Warhammer_261001")
    assert "Fallout" not in prompt
    assert glossary.load_proposals("Warhammer") == {"npc": ["Eustachy"]}


def test_cli_glossary_without_chronicles(workspace, capsys):
    assert cli.main(["glossary", "Zakon"]) == 1
    assert "nie ma jeszcze żadnych kronik" in capsys.readouterr().err


def test_pending_for_hides_names_added_meanwhile(workspace):
    glossary.save_proposals("Warhammer", {"miejsca": ["Altdorf", "Ubersreik"]})  # Altdorf jest już w słowniku
    assert glossary.pending_for(CAMPAIGN) == {"miejsca": ["Ubersreik"]}
