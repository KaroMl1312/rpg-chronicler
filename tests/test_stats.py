from rpg_chronicler import cli
from rpg_chronicler.campaigns import Campaign
from rpg_chronicler.stats import breaks_text, format_report, merge_stats, session_stats
from rpg_chronicler.transcript import Segment, Transcript, save_speaker_mapping

SEGMENTS = [Segment(10, 20, "Wchodzicie do karczmy pełnej dymu.", "SPEAKER_00"),
            Segment(20, 25, "Siadam przy kominku.", "SPEAKER_01"),
            Segment(25, 30, "I zamawiam piwo.", "SPEAKER_01"),
            Segment(30, 32, "Ja też.", "SPEAKER_02"),
            Segment(400, 410, "Wracamy po przerwie.", "SPEAKER_00"),   # 368 s ciszy = przerwa
            Segment(410, 412, "Co?", "SPEAKER_UNKNOWN"),
            Segment(412, 413, "  ", "SPEAKER_01")]                       # pusty segment się nie liczy
MAPPING = {"SPEAKER_00": "MG", "SPEAKER_01": "Ania", "SPEAKER_02": "fen"}


def test_session_stats_names_shares_and_breaks():
    campaign = Campaign(key="W", system="W", player_characters={"Fen": "", "Eustachos": "Ania"})
    stats = session_stats(Transcript(SEGMENTS, duration=500), MAPPING, campaign)
    by_name = {s.name: s for s in stats.speakers}
    assert [s.name for s in stats.speakers] == ["MG", "Eustachos", "Fen", "nierozpoznany"]  # gracz → postać
    assert by_name["MG"].seconds == 20 and by_name["MG"].utterances == 2 and by_name["MG"].words == 8
    assert by_name["Eustachos"].utterances == 1 and by_name["Eustachos"].seconds == 10
    assert stats.breaks == [(32, 400)] and stats.duration == 500
    assert stats.play_seconds == 412 - 10 - 368
    assert [s.name for s in stats.players] == ["Eustachos", "Fen"]
    assert round(stats.share(stats.gm_seconds), 2) == 0.59
    assert breaks_text(stats) == "1 przerwa, razem 6 min"
    report = format_report(stats)
    assert "MG 59% · gracze 35% czasu mówienia" in report and "Eustachos" in report


def test_merge_and_command(workspace, capsys):
    stats = session_stats(Transcript(SEGMENTS), MAPPING)
    total = merge_stats([stats, stats])
    assert total.speakers[0].name == "MG" and total.speakers[0].seconds == 40
    assert len(total.breaks) == 2 and total.play_seconds == 2 * stats.play_seconds
    assert breaks_text(session_stats(Transcript(SEGMENTS[:3]))).startswith("bez przerw")

    for name in ("Warhammer_261105", "Fallout_261014"):
        workspace.add_transcript(name, Transcript(SEGMENTS).to_txt())
        save_speaker_mapping(str(workspace.dirs["txt"] / f"{name}.txt"), MAPPING)
    assert cli.main(["stats", "--campaign", "warhammer"]) == 0
    out = capsys.readouterr().out
    assert "Warhammer_261105:" in out and "Fallout" not in out and "Razem" not in out
    assert cli.main(["stats"]) == 0
    assert "Razem, sesje: 2:" in capsys.readouterr().out
