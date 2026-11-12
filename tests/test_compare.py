from rpg_chronicler.transcription.compare import agreement, format_segments, names_found
from rpg_chronicler.transcript import Segment


def test_names_found_tolerates_polish_inflection():
    text = "Dotarliśmy do Altdorfie, Eustachosa nie było, a Sir Amos czekał."
    names = ["Altdorf", "Eustachos", "Sir Amos", "Ubersreik", "Fen"]
    assert names_found(text, names) == ["Altdorf", "Eustachos", "Sir Amos"]


def test_agreement_and_format():
    assert agreement("ala ma kota", "Ala ma kota.") == 1.0
    assert 0 < agreement("ala ma kota", "ala ma psa") < 1
    assert format_segments([Segment(65.2, 70, " Witajcie. ")]) == "[01:05] Witajcie.\n"


def test_turbo_models_transcribe_without_previous_text():
    from rpg_chronicler.transcription.compare import uses_previous_text
    assert uses_previous_text("medium") and uses_previous_text("large-v3")
    assert not uses_previous_text("large-v3-turbo") and not uses_previous_text("turbo")
