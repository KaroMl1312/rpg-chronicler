import os

from rpg_chronicler import after_chronicle, chronicle_events, cli, llm, summary
from rpg_chronicler.campaign_tools import memory
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import Segment, Transcript

LEGACY = "[0.00s -> 2.00s]  Witajcie.\n"
STATE = "## Drużyna\n- Fen: ranny\n\n## Otwarte wątki\n- Zaginiony kupiec"


def _long_transcript(minutes: int) -> str:
    segments = [Segment(i * 60.0, i * 60.0 + 50, f"wypowiedź {i}", f"SPEAKER_0{i // 4 % 2}") for i in range(minutes)]
    return Transcript(segments=segments).to_txt()


# --- stan kampanii ---

def test_state_roundtrip_with_session_header(workspace):
    memory.save_state("Fallout", STATE, "Fallout_261014")
    path = workspace.dirs["txt"] / "stan-kampanii-Fallout.md"
    assert path.read_text(encoding="utf-8").startswith("<!-- po sesji: Fallout_261014 -->\n## Drużyna")
    assert memory.load_state("Fallout") == memory.State(STATE, "Fallout_261014")
    assert [s.name for s in list_sessions()] == []   # plik stanu nie jest brany za sesję

    path.write_text("## Drużyna\n- wpisane ręcznie\n", encoding="utf-8")
    assert memory.load_state("Fallout") == memory.State("## Drużyna\n- wpisane ręcznie", None)


def test_state_only_for_later_sessions():
    state = memory.State(STATE, "Fallout_260930")
    assert memory.is_before(state, "Fallout_261014")
    assert not memory.is_before(state, "Fallout_260930")       # ta sama sesja - AI znałoby jej wynik
    assert not memory.is_before(state, "Fallout_16_09_2026")   # starsza sesja (inny format daty)
    assert memory.is_before(memory.State(STATE, None), "Fallout_16_09_2026")   # wpisany ręcznie
    assert memory.is_newer("Fallout_261014", state) and not memory.is_newer("Fallout_16_09_2026", state)


def test_accept_proposal_with_user_edits(workspace):
    memory.save_proposal("Fallout", memory.State(STATE, "Fallout_261014"))
    assert memory.accept_proposal("Fallout", text="## Drużyna\n- poprawione") == \
        memory.State("## Drużyna\n- poprawione", "Fallout_261014")
    assert memory.load_proposal("Fallout") is None
    assert memory.load_state("Fallout").text == "## Drużyna\n- poprawione"
    assert memory.accept_proposal("Fallout") is None


def test_clean_response_strips_code_fence_and_preamble():
    assert memory.clean_response(f"```markdown\nOto stan:\n{STATE}\n```") == STATE


def test_state_goes_into_chronicle_prompt(workspace):
    memory.save_state("Fallout", STATE, "Fallout_260930")
    workspace.add_transcript("Fallout_261014", LEGACY)
    workspace.add_transcript("Fallout_16_09_2026", LEGACY)
    summary.summarize_sessions(list_sessions(), interactive=False)
    old, new = workspace.llm.prompts   # sesje w kolejności nazw: 16_09_2026, potem 261014
    assert "Zaginiony kupiec" in new and "po sesji Fallout_260930" in new
    assert "Zaginiony kupiec" not in old


def test_memory_built_from_chronicles_then_updated(workspace, monkeypatch):
    monkeypatch.setattr(after_chronicle, "CAMPAIGN_MEMORY", True)
    (workspace.dirs["summary"] / "Fallout_260930_podsumowanie.txt").write_text("STARA KRONIKA", encoding="utf-8")
    workspace.add_transcript("Fallout_260930", LEGACY)
    workspace.add_transcript("Fallout_261014", LEGACY)
    workspace.add_transcript("Fallout_261028", LEGACY)
    responses = iter(["KRONIKA 1014", STATE, "KRONIKA 1028", STATE + "\n- Nowy wątek"])
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or next(responses)

    summary.summarize_sessions(list_sessions(["Fallout_261014"]), interactive=False)
    build = workspace.llm.prompts[1]
    assert "STARA KRONIKA" in build and "KRONIKA 1014" in build and "zbuduj stan od zera" in build
    assert memory.load_proposal("Fallout") == memory.State(STATE, "Fallout_261014")

    summary.summarize_sessions(list_sessions(["Fallout_261028"]), interactive=False)
    update = workspace.llm.prompts[3]
    assert "Zaginiony kupiec" in update and "KRONIKA 1028" in update and "STARA KRONIKA" not in update
    assert memory.load_proposal("Fallout").session == "Fallout_261028"   # propozycja zaktualizowana
    assert memory.load_state("Fallout") is None                          # bez zatwierdzenia nic nie zapisano


def test_old_chronicle_does_not_update_newer_state(workspace, monkeypatch):
    monkeypatch.setattr(after_chronicle, "CAMPAIGN_MEMORY", True)
    memory.save_state("Fallout", STATE, "Fallout_261014")
    workspace.add_transcript("Fallout_260930", LEGACY)
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert len(workspace.llm.prompts) == 1 and memory.load_proposal("Fallout") is None


def test_memory_command(workspace, capsys):
    assert cli.main(["memory", "Fallout"]) == 0
    assert "--rebuild" in capsys.readouterr().out
    assert cli.main(["memory", "Fallout", "--accept"]) == 1

    memory.save_proposal("Fallout", memory.State(STATE, "Fallout_261014"))
    assert cli.main(["memory", "Fallout"]) == 0
    assert "Propozycja AI (po sesji Fallout_261014)" in capsys.readouterr().out
    assert cli.main(["memory", "Fallout", "--accept"]) == 0
    assert memory.load_state("Fallout").session == "Fallout_261014"


def test_memory_rebuild_command(workspace, monkeypatch):
    from rpg_chronicler import llm
    (workspace.dirs["summary"] / "Fallout_260930_podsumowanie.txt").write_text("K1", encoding="utf-8")
    workspace.add_transcript("Fallout_260930", LEGACY)
    monkeypatch.setattr(llm, "get_client", lambda provider: workspace.llm)
    workspace.llm.response = STATE
    assert cli.main(["memory", "Fallout", "--rebuild"]) == 0
    assert memory.load_proposal("Fallout") == memory.State(STATE, "Fallout_260930")


# --- kronika w dwóch krokach ---

def test_two_step_chronicle_uses_events_and_caches_them(workspace, monkeypatch):
    monkeypatch.setattr(chronicle_events, "CHRONICLE_TWO_STEP", True)
    workspace.add_transcript("Fallout_261014", _long_transcript(100))   # 100 min -> 2 części
    counter = iter(range(100))
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or f"ODPOWIEDŹ {next(counter)}"

    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    part1, part2, final = workspace.llm.prompts
    assert "część 1 z 2" in part1 and "wypowiedź 0" in part1 and "wypowiedź 99" not in part1
    assert "część 2 z 2" in part2 and "wypowiedź 99" in part2 and "ODPOWIEDŹ 0" in part2   # kontekst
    assert "wypowiedź" not in final and "ODPOWIEDŹ 0" in final and "ODPOWIEDŹ 1" in final
    events = (workspace.dirs["summary"] / "Fallout_261014_wydarzenia.md").read_text(encoding="utf-8")
    assert "## Część 1 z 2 (0:00:00–" in events and "ODPOWIEDŹ 1" in events

    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True, force=True)
    assert len(workspace.llm.prompts) == 4   # wydarzenia z pamięci podręcznej, nowa jest tylko kronika


def test_short_session_is_summarized_in_one_step(workspace, monkeypatch):
    monkeypatch.setattr(chronicle_events, "CHRONICLE_TWO_STEP", True)
    workspace.add_transcript("Fallout_261014", _long_transcript(50))
    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    assert len(workspace.llm.prompts) == 1 and "wypowiedź 49" in workspace.llm.prompts[0]
    assert not os.path.exists(workspace.dirs["summary"] / "Fallout_261014_wydarzenia.md")


def test_campaign_section_name_used_for_memory_key(workspace, monkeypatch):
    from rpg_chronicler import campaigns
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {"Fallout": Campaign("Fallout", "Fallout 2d20")})
    memory.save_state("Fallout", STATE, None)
    workspace.add_transcript("Fallout_261014", LEGACY)
    summary.summarize_sessions(list_sessions(), interactive=False)
    assert "Zaginiony kupiec" in workspace.llm.prompts[0] and "**Fallout 2d20**" in workspace.llm.prompts[0]
