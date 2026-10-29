import random
from types import SimpleNamespace

from rpg_chronicler.transcription.merge import UNKNOWN_SPEAKER, Turn, assign_speakers


def seg(start, end):
    return SimpleNamespace(start=start, end=end)


def brute_force(segments, turns):
    """Pierwotny algorytm O(segmenty × tury) jako punkt odniesienia."""
    result = []
    for s in segments:
        speaker, max_overlap = UNKNOWN_SPEAKER, 0
        for t in sorted(turns):
            overlap = max(0, min(s.end, t.end) - max(s.start, t.start))
            if overlap > max_overlap:
                speaker, max_overlap = t.speaker, overlap
        result.append(speaker)
    return result


def test_picks_speaker_with_largest_overlap():
    turns = [Turn(0, 5, "A"), Turn(4, 10, "B")]
    assert assign_speakers([seg(3, 8)], turns) == ["B"]


def test_no_overlap_is_unknown():
    assert assign_speakers([seg(20, 25)], [Turn(0, 5, "A")]) == [UNKNOWN_SPEAKER]


def test_matches_brute_force_on_random_data():
    rng = random.Random(42)
    for _ in range(200):
        turns = []
        for _ in range(rng.randint(0, 30)):
            start = rng.uniform(0, 100)
            turns.append(Turn(start, start + rng.uniform(0.1, 20), rng.choice("ABCD")))
        starts = sorted(rng.uniform(0, 100) for _ in range(rng.randint(0, 30)))
        segments = [seg(s, s + rng.uniform(0.1, 10)) for s in starts]
        assert assign_speakers(segments, turns) == brute_force(segments, turns)
