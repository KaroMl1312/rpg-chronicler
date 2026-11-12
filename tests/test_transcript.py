import os
import tempfile

from rpg_chronicler.prompts import render
from rpg_chronicler.transcript import Segment, Transcript, load_transcript, save_transcript

TRANSCRIPT = """\
[SPEAKER_00] [0.00s -> 2.50s]  Wchodzicie do karczmy.
[SPEAKER_00] [2.50s -> 4.00s]  Jest pusto.
[SPEAKER_01] [4.00s -> 5.00s]  Rozglądam się.
[SPEAKER_UNKNOWN] [5.00s -> 6.00s]  {nawias}
"""

LEGACY_TRANSCRIPT = """\
[0.00s -> 2.00s]  To jest Fred.
[2.00s -> 3.00s]  Wygląda na Freda.
"""


def test_parses_both_txt_formats():
    t = Transcript.from_txt(TRANSCRIPT)
    assert t.segments[0] == Segment(0.0, 2.5, "Wchodzicie do karczmy.", "SPEAKER_00")
    legacy = Transcript.from_txt(LEGACY_TRANSCRIPT)
    assert legacy.segments[1] == Segment(2.0, 3.0, "Wygląda na Freda.", None)


def test_compact_strips_timestamps_and_merges_lines():
    assert Transcript.from_txt(TRANSCRIPT).compact_for_llm() == (
        "SPEAKER_00: Wchodzicie do karczmy. Jest pusto.\n"
        "SPEAKER_01: Rozglądam się.\n"
        "SPEAKER_UNKNOWN: {nawias}"
    )


def test_compact_substitutes_names():
    compact = Transcript.from_txt(TRANSCRIPT).compact_for_llm({"SPEAKER_00": "MG", "SPEAKER_01": "Hans"})
    assert compact.startswith("MG: Wchodzicie do karczmy.")
    assert "Hans: Rozglądam się." in compact


def test_compact_keeps_legacy_lines_separate():
    assert Transcript.from_txt(LEGACY_TRANSCRIPT).compact_for_llm() == "To jest Fred.\nWygląda na Freda."


def test_speakers_ignore_unknown():
    assert Transcript.from_txt(TRANSCRIPT).speakers == ["SPEAKER_00", "SPEAKER_01"]
    assert Transcript.from_txt(LEGACY_TRANSCRIPT).speakers == []


def test_save_and_load_json_and_txt():
    t = Transcript.from_txt(TRANSCRIPT)
    t.audio, t.duration = "sesja.m4a", 6.0
    with tempfile.TemporaryDirectory() as tmp:
        json_path, txt_path = os.path.join(tmp, "s.transkrypcja.json"), os.path.join(tmp, "s.txt")
        save_transcript(t, json_path, txt_path)
        assert load_transcript(json_path, txt_path) == t
        with open(txt_path, encoding="utf-8") as f:
            assert Transcript.from_txt(f.read()).segments == t.segments
        os.remove(json_path)  # bez JSON wczytujemy starszy .txt
        assert load_transcript(json_path, txt_path).segments == t.segments


def test_prompts_render_with_braces_in_transcript():
    prompt = render("summary", system_name="Warhammer", speaker_mapping_info="", campaign_context="",
                    source=Transcript.from_txt(TRANSCRIPT).compact_for_llm())
    assert "**Warhammer**" in prompt and "{nawias}" in prompt
    assert "Warhammer" in render("speaker_identification", system_name="Warhammer", campaign_info="", transcript="x")
    events = render("events", system_name="Warhammer", part="1", parts="2", time_range="0:00:00–0:45:00",
                    speaker_mapping_info="", campaign_context="", previous_events="", transcript="{x}")
    assert "część 1 z 2" in events and "{x}" in events
    state = render("campaign_state", system_name="Warhammer", campaign_info="", previous_state="{k}")
    assert "## Otwarte wątki" in state and "{k}" in state


def test_split_parts_cuts_at_speaker_change_and_merges_short_tail():
    segments = [Segment(i * 60.0, i * 60.0 + 50, f"t{i}", f"SPEAKER_0{i // 4 % 2}") for i in range(100)]
    parts = Transcript(segments=segments).split_parts(45 * 60)
    assert [len(p.segments) for p in parts] == [48, 52]   # cięcie przy zmianie mówcy po 45 min, krótka końcówka dołączona
    assert parts[0].segments[-1].speaker != parts[1].segments[0].speaker
    assert sum(len(p.segments) for p in parts) == 100
    assert len(Transcript(segments=segments[:30]).split_parts(45 * 60)) == 1


def test_speaker_samples_merge_consecutive_segments_and_pick_longest():
    transcript = Transcript(segments=[
        Segment(0.0, 2.0, "Witajcie", "SPEAKER_00"),
        Segment(2.5, 6.0, "w karczmie.", "SPEAKER_00"),   # przerwa 0,5 s -> ta sama wypowiedź
        Segment(6.0, 7.0, "Hej!", "SPEAKER_01"),
        Segment(7.0, 8.0, "Kto tam?", "SPEAKER_00"),
        Segment(20.0, 21.0, "  ", "SPEAKER_00"),          # pusty tekst pomijamy
        Segment(30.0, 33.0, "Dalej.", "SPEAKER_00"),
    ])
    samples = transcript.speaker_samples("SPEAKER_00", limit=2)
    assert [(s.start, s.end, s.text) for s in samples] == [(0.0, 6.0, "Witajcie w karczmie."), (30.0, 33.0, "Dalej.")]
    assert transcript.speaker_samples("SPEAKER_00", limit=5, max_duration=3.0)[0].end == 2.0


def test_speaker_stats():
    transcript = Transcript.from_txt(TRANSCRIPT)
    assert transcript.speaker_stats()["SPEAKER_00"] == (2, 4.0)
    assert transcript.speaker_stats()["SPEAKER_01"] == (1, 1.0)
