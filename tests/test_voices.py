import json
import math

from rpg_chronicler import cli, voices
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.session import list_sessions
from rpg_chronicler.speakers import ask_speaker_names
from rpg_chronicler.transcript import Transcript, save_speaker_mapping
from rpg_chronicler.voices import NameResolver, Suggestion, Voiceprint

CAMPAIGN = Campaign("Warhammer", "WFRP", player_characters={"Fen": "Ania", "Eustachos": ""})


def vp(*values, seconds=60.0):
    return Voiceprint(voices._normalized(values), seconds)


def angle(degrees):
    """Wektor 2D pod kątem - podobieństwo kosinusowe dwóch takich wektorów = cos(różnicy kątów)."""
    return vp(math.cos(math.radians(degrees)), math.sin(math.radians(degrees)))


def test_name_resolver_unifies_case_typos_and_players():
    resolver = NameResolver(CAMPAIGN)
    assert resolver.resolve("mg") == "MG"
    assert resolver.resolve("Eustahos") == "Eustachos"  # literówka
    assert resolver.resolve("Ania") == "Fen"            # imię gracza -> jego postać
    assert resolver.resolve("Kate") == "Kate" and resolver.resolve("kate") == "Kate"


def test_suggest_confident_possible_and_none():
    profiles = {"Fen": [angle(0)], "MG": [angle(90)]}
    suggestions = voices.suggest({"SPEAKER_00": angle(10),     # cos 10° = 0.98, wyraźnie Fen
                                  "SPEAKER_01": angle(47),     # między Fen a MG: 0.73 vs 0.68, przewaga za mała
                                  "SPEAKER_02": angle(-80)}, profiles)  # nikt znany
    assert suggestions["SPEAKER_00"].name == "Fen" and suggestions["SPEAKER_00"].confident
    assert suggestions["SPEAKER_01"].name == "MG" and not suggestions["SPEAKER_01"].confident
    assert "SPEAKER_02" not in suggestions
    assert voices.suggest({"SPEAKER_00": angle(0)}, {}) == {}


def test_save_load_roundtrip_and_other_model_ignored(tmp_path):
    path = str(tmp_path / "Zakon_1.glosy.json")
    voices.save_voiceprints(path, {"SPEAKER_00": vp(3, 4, seconds=90)})
    loaded = voices.load_voiceprints(path)
    assert loaded["SPEAKER_00"].seconds == 90 and abs(loaded["SPEAKER_00"].vector[0] - 0.6) < 1e-6
    data = json.loads(open(path, encoding="utf-8").read())
    data["model"] = "inny/model"
    open(path, "w", encoding="utf-8").write(json.dumps(data))
    assert voices.load_voiceprints(path) == {}


def test_profiles_from_named_sessions_of_same_campaign(workspace):
    for name in ("Warhammer_261001", "Warhammer_261015", "Fallout_261014", "Warhammer_261105"):
        workspace.add_transcript(name, "[SPEAKER_00] [0.00s -> 1.00s] x\n")
    sessions = {s.name: s for s in list_sessions()}
    voices.save_voiceprints(voices.voices_path(sessions["Warhammer_261001"]), {"SPEAKER_00": angle(0)})
    voices.save_voiceprints(voices.voices_path(sessions["Warhammer_261015"]), {"SPEAKER_00": angle(5)})
    voices.save_voiceprints(voices.voices_path(sessions["Fallout_261014"]), {"SPEAKER_00": angle(90)})
    voices.save_voiceprints(voices.voices_path(sessions["Warhammer_261105"]), {"SPEAKER_00": angle(2)})
    save_speaker_mapping(sessions["Warhammer_261001"].txt_path, {"SPEAKER_00": "Ania"})
    save_speaker_mapping(sessions["Warhammer_261015"].txt_path, {"SPEAKER_00": "fen"})
    save_speaker_mapping(sessions["Fallout_261014"].txt_path, {"SPEAKER_00": "Wei"})  # inna kampania

    profiles = voices.campaign_profiles(CAMPAIGN, exclude="Warhammer_261105")
    assert list(profiles) == ["Fen"] and len(profiles["Fen"]) == 2

    suggestion = voices.suggest(voices.load_voiceprints(voices.voices_path(sessions["Warhammer_261105"])), profiles)
    assert suggestion["SPEAKER_00"].name == "Fen"
    assert [s.name for s in voices.learning_candidates(CAMPAIGN)] == []  # nazwane mają już odciski


def test_learning_candidates_need_audio_names_and_no_voiceprints(workspace):
    workspace.add_audio("Warhammer_261001")
    workspace.add_transcript("Warhammer_261001", "[SPEAKER_00] [0.00s -> 1.00s] x\n")
    workspace.add_transcript("Warhammer_261015", "[SPEAKER_00] [0.00s -> 1.00s] x\n")  # bez nagrania
    for session in list_sessions():
        save_speaker_mapping(session.txt_path, {"SPEAKER_00": "MG"})
    assert [s.name for s in voices.learning_candidates(CAMPAIGN)] == ["Warhammer_261001"]


def test_voiceprints_file_is_not_a_session(workspace):
    workspace.add_transcript("Zakon_1", "[SPEAKER_00] [0.00s -> 1.00s] x\n")
    voices.save_voiceprints(voices.voices_path(list_sessions()[0]), {"SPEAKER_00": angle(0)})
    assert [s.name for s in list_sessions()] == ["Zakon_1"]


def test_terminal_naming_accepts_confident_voice_suggestion(monkeypatch):
    transcript = Transcript.from_txt("[SPEAKER_00] [0.00s -> 1.00s] a\n[SPEAKER_01] [1.00s -> 2.00s] b\n"
                                     "[SPEAKER_02] [2.00s -> 3.00s] c\n")
    suggestions = {"SPEAKER_00": Suggestion("Fen", 0.8, True), "SPEAKER_01": Suggestion("MG", 0.55, False),
                   "SPEAKER_02": Suggestion("Fen", 0.9, True)}
    answers = iter(["", "", "-"])  # Enter przyjmuje pewną, przy niepewnej pomija, „-” pomija pewną
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or next(answers))
    assert ask_speaker_names(transcript, suggestions) == {"SPEAKER_00": "Fen"}
    assert "[Fen]" in prompts[0] and "(może MG, 55%)" in prompts[1]


def test_cli_voices_without_audio_does_nothing(workspace, capsys):
    workspace.add_transcript("Zakon_1", "[SPEAKER_00] [0.00s -> 1.00s] x\n")
    assert cli.main(["voices", "--no-suggest"]) == 0
    assert "Brak sesji do przetworzenia" in capsys.readouterr().out
