from rpg_chronicler.prompts import render
from rpg_chronicler.session import system_name_from_filename
from rpg_chronicler.transcript import compact_for_llm, detect_speakers

TRANSCRIPT = """\
[SPEAKER_00] [0.00s -> 2.50s]  Wchodzicie do karczmy.
[SPEAKER_00] [2.50s -> 4.00s]  Jest pusto.
[SPEAKER_01] [4.00s -> 5.00s]  Rozglądam się.
[SPEAKER_UNKNOWN] [5.00s -> 6.00s]  {nawias}
"""


def test_compact_strips_timestamps_and_merges_lines():
    assert compact_for_llm(TRANSCRIPT) == (
        "SPEAKER_00: Wchodzicie do karczmy. Jest pusto.\n"
        "SPEAKER_01: Rozglądam się.\n"
        "SPEAKER_UNKNOWN: {nawias}"
    )


def test_compact_substitutes_names():
    compact = compact_for_llm(TRANSCRIPT, {"SPEAKER_00": "MG", "SPEAKER_01": "Hans"})
    assert compact.startswith("MG: Wchodzicie do karczmy.")
    assert "Hans: Rozglądam się." in compact


def test_detect_speakers_ignores_unknown():
    assert detect_speakers(TRANSCRIPT) == ["SPEAKER_00", "SPEAKER_01"]


def test_system_name_from_filename():
    assert system_name_from_filename("warhammer-fantasy_sesja12.txt") == "Warhammer Fantasy"
    assert system_name_from_filename("sesja.txt") == "RPG"


def test_prompts_render_with_braces_in_transcript():
    prompt = render("summary", system_name="Warhammer", speaker_mapping_info="",
                    transcript=compact_for_llm(TRANSCRIPT))
    assert "**Warhammer**" in prompt and "{nawias}" in prompt
    assert "Warhammer" in render("speaker_identification", system_name="Warhammer", transcript="x")
