"""Logika GUI bez GTK (rpg_chronicler.gui.text nie importuje gi)."""
from rpg_chronicler.gui.text import (estimate_remaining, format_minutes, format_timestamp, markdown_spans,
                                     session_stage, transcript_blocks)
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import Segment, Transcript, save_speaker_mapping


def test_formatting():
    assert format_timestamp(3725.9) == "1:02:05"
    assert format_minutes(59 * 60) == "59 min"
    assert format_minutes(125 * 60) == "2 h 05 min"


def test_session_stage(workspace):
    workspace.add_audio("Zakon_1")
    assert session_stage(list_sessions()[0]) == ("czeka na transkrypcję", False)

    workspace.add_transcript("Zakon_1", "[SPEAKER_00] [0.00s -> 1.00s] Witajcie.\n")
    assert session_stage(list_sessions()[0]) == ("mówcy bez imion", False)

    save_speaker_mapping(list_sessions()[0].txt_path, {"SPEAKER_00": "MG"})
    assert session_stage(list_sessions()[0]) == ("czeka na kronikę", False)

    (workspace.dirs["summary"] / "Zakon_1_podsumowanie.txt").write_text("K", encoding="utf-8")
    assert session_stage(list_sessions()[0]) == ("gotowe", True)


def test_old_transcript_without_speakers_does_not_need_names(workspace):
    workspace.add_transcript("Zakon_2", "[0.00s -> 1.00s] Bez mówców.\n")
    assert session_stage(list_sessions()[0]) == ("czeka na kronikę", False)


def test_transcript_blocks_merge_same_speaker_and_apply_names():
    transcript = Transcript(segments=[
        Segment(0, 1, "Witajcie.", "SPEAKER_00"), Segment(1, 2, "Zaczynamy.", "SPEAKER_00"),
        Segment(2, 3, "Hej.", "SPEAKER_01"), Segment(3, 4, "Bez mówcy."), Segment(4, 5, "Druga linia."),
    ])
    assert transcript_blocks(transcript, {"SPEAKER_00": "MG"}) == [
        (0, "MG", "Witajcie. Zaczynamy."), (2, "SPEAKER_01", "Hej."),
        (3, None, "Bez mówcy."), (4, None, "Druga linia."),
    ]


def test_markdown_spans():
    assert markdown_spans("## 🌿 **Tytuł**") == ("h2", [("🌿 ", None), ("Tytuł", "bold")])
    assert markdown_spans("* **Sojusz:** tekst") == ("", [("•  ", None), ("Sojusz:", "bold"), (" tekst", None)])
    assert markdown_spans("---") == ("rule", [])
    assert markdown_spans("Zwykły tekst") == ("", [("Zwykły tekst", None)])


def test_estimate_remaining():
    assert estimate_remaining(10, 0.5) is None      # za wcześnie na szacowanie
    assert estimate_remaining(600, 0.25) == 1800
