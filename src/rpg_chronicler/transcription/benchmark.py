"""Pomiar szybkości (i porównanie jakości) transkrypcji i diaryzacji na fragmencie nagrania."""
import os
import time

import torch
from faster_whisper import decode_audio

from .compare import agreement, format_segments, names_found, words
from .runner import diarize, format_duration, load_diarization, load_whisper, transcribe_audio

SAMPLE_RATE = 16000


def run_benchmark(audio_path: str, seconds: int, *, threads: list[int], vad: bool,
                  batch_size: int, diarization: bool, diarization_models: list[str],
                  whisper_models: list[str], offset: int = 0, hotwords: str | None = None,
                  names: list[str] | None = None, save_text: str | None = None) -> None:
    print(f"Wczytywanie nagrania {audio_path}...")
    full_audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)
    full_duration = len(full_audio) / SAMPLE_RATE
    audio = full_audio[offset * SAMPLE_RATE: (offset + seconds) * SAMPLE_RATE]
    sample_duration = len(audio) / SAMPLE_RATE
    if sample_duration <= 0:
        raise ValueError(f"Nagranie trwa {format_duration(full_duration)} - przesunięcie {offset} s jest za duże.")
    scale = full_duration / sample_duration
    print(f"Fragment: {format_duration(sample_duration)} od {format_duration(offset)} "
          f"(nagranie: {format_duration(full_duration)})"
          + (", z podpowiedzią nazw kampanii" if hotwords else "") + "\n")

    results = []
    texts: dict[str, str] = {}

    for model_name in diarization_models if diarization else []:
        pipeline = load_diarization(model_name)
        started = time.perf_counter()
        turns = diarize(pipeline, {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE})
        elapsed = time.perf_counter() - started
        results.append((f"głosy: {model_name.split('/')[-1]}", elapsed, f"{len({t.speaker for t in turns})} mówców"))

    mode = f"wsadowo ({batch_size})" if batch_size > 0 else ("z VAD" if vad else "bez VAD")
    for whisper_name in whisper_models:
        for n in threads if threads else []:
            print(f"Whisper {whisper_name}, {n} wątków ({mode})...")
            model = load_whisper(cpu_threads=n, model_size=whisper_name)
            started = time.perf_counter()
            segments, _ = transcribe_audio(model, audio, vad=vad, batch_size=batch_size, show_progress=False,
                                           hotwords=hotwords, model_size=whisper_name)
            elapsed = time.perf_counter() - started
            text = format_segments(segments)
            texts.setdefault(whisper_name, text)
            note = f"{len(segments)} segm., {len(words(text))} słów"
            if names:
                note += f", nazwy kampanii: {len(names_found(text, names))}"
            results.append((f"whisper {whisper_name}, {n} wątków, {mode}", elapsed, note))
            del model

    print(f"\n{'ETAP':<48} {'CZAS':>10} {'x CZAS RZECZ.':>14} {'CAŁE NAGRANIE (szac.)':>22}  WYNIK")
    for name, elapsed, note in results:
        print(f"{name:<48} {format_duration(elapsed):>10} {elapsed / sample_duration:>13.2f}x "
              f"{format_duration(elapsed * scale):>22}  {note}")

    if len(texts) > 1:
        print("\nZgodność słów między modelami (100% = identyczne teksty):")
        models = list(texts)
        for i, a in enumerate(models):
            for b in models[i + 1:]:
                print(f"  {a} ↔ {b}: {agreement(texts[a], texts[b]):.0%}")
    if names and texts:
        print("\nNazwy ze słownika kampanii w tekście:")
        for model_name, text in texts.items():
            print(f"  {model_name}: {', '.join(names_found(text, names)) or '-'}")
    if save_text:
        os.makedirs(save_text, exist_ok=True)
        for model_name, text in texts.items():
            path = os.path.join(save_text, f"{model_name}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[SUKCES] Tekst {model_name}: {path}")
