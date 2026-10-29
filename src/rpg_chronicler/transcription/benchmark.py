"""Pomiar szybkości transkrypcji i diaryzacji na fragmencie nagrania."""
import time

import torch
from faster_whisper import decode_audio

from .runner import diarize, format_duration, load_diarization, load_whisper, transcribe_audio

SAMPLE_RATE = 16000


def run_benchmark(audio_path: str, seconds: int, *, threads: list[int], vad: bool,
                  batch_size: int, diarization: bool, diarization_models: list[str]) -> None:
    print(f"Wczytywanie nagrania {audio_path}...")
    full_audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    full_duration = len(full_audio) / SAMPLE_RATE
    audio = full_audio[: seconds * SAMPLE_RATE]
    sample_duration = len(audio) / SAMPLE_RATE
    scale = full_duration / sample_duration
    print(f"Fragment: {format_duration(sample_duration)} z {format_duration(full_duration)}\n")

    results = []

    for model_name in diarization_models if diarization else []:
        pipeline = load_diarization(model_name)
        started = time.perf_counter()
        turns = diarize(pipeline, {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE})
        elapsed = time.perf_counter() - started
        results.append((f"głosy: {model_name.split('/')[-1]}", elapsed, f"{len({t.speaker for t in turns})} mówców"))

    mode = f"wsadowo ({batch_size})" if batch_size > 0 else ("z VAD" if vad else "bez VAD")
    for n in threads if threads else []:
        model = load_whisper(cpu_threads=n)
        started = time.perf_counter()
        segments, _ = transcribe_audio(model, audio, vad=vad, batch_size=batch_size, show_progress=False)
        elapsed = time.perf_counter() - started
        results.append((f"whisper, {n} wątków, {mode}", elapsed, f"{len(segments)} segmentów"))

    print(f"\n{'ETAP':<40} {'CZAS':>10} {'x CZAS RZECZ.':>14} {'CAŁE NAGRANIE (szac.)':>22}  WYNIK")
    for name, elapsed, note in results:
        print(f"{name:<40} {format_duration(elapsed):>10} {elapsed / sample_duration:>13.2f}x "
              f"{format_duration(elapsed * scale):>22}  {note}")
