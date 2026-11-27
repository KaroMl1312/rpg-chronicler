"""Wczytywanie bardzo długich nagrań po kawałkach (wymaga torcha - w CI pomijane)."""
import pytest

torch = pytest.importorskip("torch")
functional = pytest.importorskip("torchaudio.functional")
pytest.importorskip("torchcodec.decoders")

from rpg_chronicler.transcription import audio  # noqa: E402


@pytest.mark.parametrize("rate", [48000, 44100, 22050])
def test_blocks_give_the_same_audio_as_whole_file(rate):
    mono = torch.randn(rate * 13 + 777)
    whole = functional.resample(mono[None], rate, audio.TARGET_RATE)
    blocks = audio.resample_blocks(lambda first, last: mono[first:last], len(mono), rate, block_seconds=4)
    length = min(whole.shape[1], blocks.shape[1])
    assert abs(whole.shape[1] - blocks.shape[1]) <= 1  # torchaudio zaokrągla długość
    assert torch.allclose(whole[:, :length], blocks[:, :length], atol=1e-6)


def test_block_never_exceeds_margin():
    mono, sizes = torch.zeros(48000 * 30), []

    def read(first, last):
        sizes.append(last - first)
        return mono[first:last]
    audio.resample_blocks(read, len(mono), 48000, block_seconds=5)
    assert max(sizes) <= 48000 * (5 + 2 * audio.MARGIN_SECONDS) and len(sizes) == 6


def test_limit():
    assert audio.is_too_long(4 * 3600 * 48000, 48000)       # 4 h nagrania z dyktafonu
    assert not audio.is_too_long(10491 * 48000 - 4_000_000, 48000)
    assert not audio.is_too_long(20 * 3600 * 16000, 16000)  # 16 kHz nie wymaga przeliczania
    assert audio.MAX_SAMPLES * 4 < 2 ** 31


class _Metadata:
    def __init__(self, duration, rate):
        self.duration_seconds_from_header, self.sample_rate = duration, rate


@pytest.mark.parametrize("duration,long", [(2 * 3600, False), (4 * 3600, True), (None, False)])
def test_only_long_recordings_are_loaded_by_us(monkeypatch, capsys, duration, long):
    class Decoder:
        def __init__(self, path):
            self.metadata = _Metadata(duration, 48000)
    monkeypatch.setattr(audio, "AudioDecoder", Decoder)
    monkeypatch.setattr(audio, "load_waveform", lambda path: "dźwięk")
    result = audio.load_for_diarization("sesja.m4a")
    assert result == ({"waveform": "dźwięk", "sample_rate": 16000} if long else "sesja.m4a")
    assert ("po kawałkach" in capsys.readouterr().out) == long
