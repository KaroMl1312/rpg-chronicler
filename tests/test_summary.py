from rpg_chronicler import after_chronicle, summary
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import save_speaker_mapping

TRANSCRIPT = "[SPEAKER_00] [0.00s -> 2.00s]  Witajcie w Altdorfie.\n"
LEGACY = "[0.00s -> 2.00s]  Witajcie w Altdorfie.\n"


def test_non_interactive_skips_sessions_without_speakers(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert workspace.llm.prompts == []
    assert not list_sessions()[0].has_summary


def test_allow_unnamed_summarizes_without_speakers(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    assert list_sessions()[0].has_summary
    assert "SPEAKER_00: Witajcie w Altdorfie." in workspace.llm.prompts[0]


def test_legacy_transcript_without_speakers_is_not_skipped(workspace):
    workspace.add_transcript("Warhammer_1", LEGACY)
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert "\nWitajcie w Altdorfie." in workspace.llm.prompts[0]


def test_uses_saved_speaker_names_and_skips_existing_summaries(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    save_speaker_mapping(list_sessions()[0].txt_path, {"SPEAKER_00": "MG"})
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert "MG: Witajcie w Altdorfie." in workspace.llm.prompts[0]
    assert "**Warhammer**" in workspace.llm.prompts[0]

    summary.summarize_sessions(list_sessions(), interactive=False)
    assert len(workspace.llm.prompts) == 1


def test_force_regenerates_summary(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True, force=True)
    assert len(workspace.llm.prompts) == 2


def test_interactive_asks_and_saves_speaker_names(workspace, monkeypatch):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    answers = iter(["y", "MG"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    summary.summarize_sessions(list_sessions(), interactive=True)

    session = list_sessions()[0]
    assert session.has_speakers and session.has_summary
    identification, chronicle = workspace.llm.prompts
    assert "SPEAKER_00: Witajcie" in identification
    assert "MG: Witajcie" in chronicle


def test_name_speakers_skips_transcripts_without_speakers(workspace):
    workspace.add_transcript("Warhammer_1", LEGACY)
    summary.name_speakers(list_sessions())
    assert workspace.llm.prompts == []


def test_campaign_context_goes_into_prompt(workspace, monkeypatch):
    from rpg_chronicler import campaigns
    from rpg_chronicler.campaigns import Campaign
    monkeypatch.setattr(campaigns, "load_campaigns",
                        lambda: {"Warhammer": Campaign("Warhammer", "WFRP", "Altdorf, rok 2512.")})
    workspace.add_transcript("Warhammer_1", LEGACY)
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert "**WFRP**" in workspace.llm.prompts[0]
    assert "Altdorf, rok 2512." in workspace.llm.prompts[0]


def test_select_sessions_by_name_or_filename(workspace):
    workspace.add_transcript("Warhammer_1", TRANSCRIPT)
    workspace.add_audio("Fallout_2")
    assert [s.name for s in list_sessions(["Fallout_2.m4a"])] == ["Fallout_2"]
    assert [s.name for s in list_sessions()] == ["Fallout_2", "Warhammer_1"]


def test_previous_chronicle_of_same_campaign_goes_into_prompt(workspace):
    workspace.add_transcript("Fallout_16_09_2026", LEGACY)
    workspace.add_transcript("Fallout_260930", LEGACY)
    workspace.add_transcript("Fallout_261014", LEGACY)
    workspace.add_transcript("Warhammer_261001", LEGACY)
    for name, text in (("Fallout_16_09_2026", "STARA KRONIKA"), ("Fallout_260930", "POPRZEDNIA KRONIKA"),
                       ("Warhammer_261001", "INNA KAMPANIA")):
        (workspace.dirs["summary"] / f"{name}_podsumowanie.txt").write_text(name and text, encoding="utf-8")

    summary.summarize_sessions(list_sessions(["Fallout_261014"]), interactive=False)
    prompt = workspace.llm.prompts[0]
    assert "POPRZEDNIA KRONIKA" in prompt and "Fallout_260930" in prompt
    assert "STARA KRONIKA" not in prompt and "INNA KAMPANIA" not in prompt


def test_glossary_proposals_after_new_chronicle(workspace, monkeypatch):
    from rpg_chronicler.campaign_tools import glossary
    monkeypatch.setattr(after_chronicle, "GLOSSARY_PROPOSALS", True)
    responses = iter(["KRONIKA o Altdorfie", '{"npc": ["Eustachy"], "miejsca": ["Altdorf"], "opis": "Imperium."}'])
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or next(responses)
    workspace.add_transcript("Warhammer_261001", LEGACY)

    summary.summarize_sessions(list_sessions(), interactive=False)
    assert "KRONIKA o Altdorfie" in workspace.llm.prompts[1]  # kronika trafiła do zapytania o słownik
    assert glossary.load_proposals("Warhammer") == {"npc": ["Eustachy"], "miejsca": ["Altdorf"], "opis": "Imperium."}
