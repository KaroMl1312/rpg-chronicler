"""Wczytywanie nagrań do rozpoznawania głosów.

Pyannote przepróbkowuje całe nagranie naraz, a torch nie radzi sobie z tensorem powyżej 2 GB
(„could not create a primitive”) - przy 48 kHz to ok. 3 h 6 min. Takie nagrania wczytujemy sami po kawałkach.
"""
import torch
import torchaudio.functional
from torchcodec.decoders import AudioDecoder

TARGET_RATE = 16000            # częstotliwość modeli pyannote
MAX_SAMPLES = 500_000_000      # float32: 2 GB, trochę poniżej granicy torcha (2^31 bajtów)
BLOCK_SECONDS = 600            # pełne sekundy - granice kawałków wypadają na całych próbkach przed i po zmianie
MARGIN_SECONDS = 1             # zapas z obu stron, żeby filtr nie słyszał granic kawałków


def is_too_long(samples: int, sample_rate: int) -> bool:
    """Czy pyannote nie przeliczy tego nagrania samo (16 kHz nie wymaga przeliczania)."""
    return sample_rate != TARGET_RATE and samples > MAX_SAMPLES


def resample_blocks(read, samples: int, sample_rate: int, *, block_seconds: int = BLOCK_SECONDS) -> torch.Tensor:
    """Mono 16 kHz (1, próbki) z nagrania czytanego po kawałkach.

    `read(początek, koniec)` zwraca próbki mono o podanych numerach. Wynik jest taki sam
    jak przy przeliczeniu całości naraz.
    """
    total = -(-samples * TARGET_RATE // sample_rate)
    result = torch.zeros(1, total, dtype=torch.float32)
    block, margin = block_seconds * sample_rate, MARGIN_SECONDS * sample_rate
    for start in range(0, samples, block):
        first = max(0, start - margin)
        part = read(first, min(samples, start + block + margin))
        part = torchaudio.functional.resample(part[None], sample_rate, TARGET_RATE)
        skip = (start - first) * TARGET_RATE // sample_rate
        position = start * TARGET_RATE // sample_rate
        # ostatni kawałek bywa o próbkę krótszy - torchaudio zaokrągla długość
        count = min(block * TARGET_RATE // sample_rate, total - position, part.shape[1] - skip)
        result[:, position:position + count] = part[:, skip:skip + count]
    return result


def load_waveform(audio_path: str) -> torch.Tensor:
    """Całe nagranie jako mono 16 kHz (1, próbki)."""
    samples = AudioDecoder(audio_path).get_all_samples()
    sample_rate, audio = samples.sample_rate, samples.data
    del samples
    mono = audio.mean(dim=0) if len(audio) > 1 else audio[0]
    del audio
    if sample_rate == TARGET_RATE:
        return mono[None]
    return resample_blocks(lambda first, last: mono[first:last], len(mono), sample_rate)


def load_for_diarization(audio_path: str):
    """To, co dostaje pyannote: ścieżka, a dla zbyt długiego nagrania - gotowy dźwięk 16 kHz."""
    metadata = AudioDecoder(audio_path).metadata
    duration, sample_rate = metadata.duration_seconds_from_header, metadata.sample_rate
    if not duration or not sample_rate or not is_too_long(round(duration * sample_rate), sample_rate):
        return audio_path
    print("[INFO] Bardzo długie nagranie - wczytywanie po kawałkach...")
    return {"waveform": load_waveform(audio_path), "sample_rate": TARGET_RATE}
