from rpg_chronicler import cli, quality
from rpg_chronicler.transcript import Segment, Transcript


def _speech(minutes: float, words_per_segment: int = 8, seg_len: float = 4.0, start: float = 0.0):
    """Gęsta mowa: segmenty co `seg_len` s (8 słów / 4 s = 120 słów na minutę), za każdym razem inny tekst."""
    count = int(minutes * 60 / seg_len)
    return [Segment(start + i * seg_len, start + (i + 1) * seg_len,
                    " ".join(f"słowo{i}_{k}" for k in range(words_per_segment))) for i in range(count)]


def kinds(issues):
    return [i.kind for i in issues]


def test_normal_session_has_no_issues():
    assert quality.check(Transcript(_speech(60))) == []


def test_short_recording_and_little_text():
    assert kinds(quality.check(Transcript(_speech(20)))) == ["krotkie_nagranie"]
    sparse = Transcript(_speech(60, words_per_segment=1))  # 15 słów na minutę
    assert "malo_tekstu" in kinds(quality.check(sparse))


def test_gap_and_cut_off_end():
    segments = _speech(30) + _speech(30, start=30 * 60 + 6 * 60)
    issues = quality.check(Transcript(segments), audio_duration=90 * 60)
    assert kinds(issues) == ["brak_konca", "dziura"]
    assert issues[1].at == 30 * 60


def test_whisper_loop_detected_but_short_repeats_are_natural():
    loop = [Segment(3600 + 2 * i, 3602 + 2 * i, " To jest to") for i in range(10)]
    issues = quality.check(Transcript(_speech(60) + loop))
    assert kinds(issues) == ["petla"] and "10×" in issues[0].message and issues[0].at == 3600
    natural = [Segment(3600 + i, 3601 + i, "Nie, nie.") for i in range(10)]
    assert quality.check(Transcript(_speech(60) + natural)) == []


def test_check_command_reports_duplicates(workspace, capsys):
    text = Transcript(_speech(60)).to_txt()
    workspace.add_transcript("Fallout_1", text)
    workspace.add_transcript("BEZ_Fallout_1", text.replace("[0.00s", "[0.10s"))
    workspace.add_transcript("Fallout_2", Transcript(_speech(61)).to_txt())
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "Ta sama treść co: Fallout_1" in out and "Ta sama treść co: BEZ_Fallout_1" in out
    assert "3 transkrypcji: 1 bez uwag, 2 z uwagami" in out

    assert cli.main(["status"]) == 0
    assert "rpg-chronicler check" in capsys.readouterr().out
