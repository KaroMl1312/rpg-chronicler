import os
import time

from faster_whisper import BatchedInferencePipeline, WhisperModel
from pyannote.audio import Pipeline
from tqdm import tqdm

from .. import progress
from ..audio_trim import has_duration_header
from ..config import (
    DIARIZATION_MODEL,
    HUGGINGFACE_TOKEN,
    MODEL_SIZE,
    TXT_DIR,
    WHISPER_BATCH_SIZE,
    WHISPER_CPU_THREADS,
    WHISPER_NAME_HINTS,
    WHISPER_VAD,
)
from ..session import Session
from ..transcript import Segment, Transcript, save_transcript
from ..voices import save_voiceprints, voices_path
from .compare import uses_previous_text
from .merge import Turn, assign_speakers


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"


def load_whisper(cpu_threads: int = WHISPER_CPU_THREADS, model_size: str = MODEL_SIZE) -> WhisperModel:
    return WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)


def load_diarization(model: str = DIARIZATION_MODEL) -> Pipeline:
    return Pipeline.from_pretrained(model, token=HUGGINGFACE_TOKEN)


def _progress_hook(session_name: str | None):
    """Hook pyannote zgłaszający postęp kolejnych etapów diaryzacji (tylko w trybie dla GUI)."""
    names = {"segmentation": "segmentacja", "speaker_counting": "liczenie mówców",
             "embeddings": "cechy głosów", "discrete_diarization": "przypisanie"}

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        if total is None:
            return  # zakończenie etapu - kolejny i tak zgłosi swój postęp
        step = names.get(step_name, step_name)
        progress.report(f"rozpoznawanie głosów: {step}", session_name, completed, total)
    return hook


def diarize(pipeline: Pipeline, audio, session_name: str | None = None) -> list[Turn]:
    """`audio` to ścieżka do pliku albo {"waveform": tensor, "sample_rate": int}."""
    if progress.enabled():
        diarization = pipeline(audio, hook=_progress_hook(session_name))
    else:
        diarization = pipeline(audio)
    return [Turn(turn.start, turn.end, spk)
            for turn, _, spk in diarization.speaker_diarization.itertracks(yield_label=True)]


def transcribe_audio(whisper_model: WhisperModel, audio, *, vad: bool = WHISPER_VAD,
                     batch_size: int = WHISPER_BATCH_SIZE, show_progress: bool = True,
                     session_name: str | None = None, hotwords: str | None = None,
                     model_size: str = MODEL_SIZE):
    """Zwraca (lista segmentów, info). `audio` to ścieżka albo tablica numpy 16 kHz.

    `hotwords`: nazwy podpowiadane modelowi (słownik kampanii) - poprawiają pisownię imion i miejsc.
    `model_size`: nazwa modelu - modele turbo działają bez warunkowania na poprzednim tekście (compare.py).
    """
    if batch_size > 0:
        segments_iter, info = BatchedInferencePipeline(whisper_model).transcribe(
            audio, language="pl", batch_size=batch_size, hotwords=hotwords)
    else:
        segments_iter, info = whisper_model.transcribe(
            audio, language="pl", vad_filter=vad, hotwords=hotwords,
            condition_on_previous_text=uses_previous_text(model_size))

    # Segmenty powstają w trakcie iterowania - stąd postęp liczony po czasie nagrania
    segments = []
    report = show_progress and progress.enabled()
    with tqdm(total=round(info.duration), unit="s", desc="Transkrypcja",
              disable=not show_progress or report) as bar:
        for segment in segments_iter:
            segments.append(segment)
            bar.update(max(0, min(round(segment.end), bar.total) - bar.n))
            if report:
                progress.report("transkrypcja", session_name, min(segment.end, info.duration), info.duration)
    return segments, info


def name_hints(session: Session) -> str | None:
    """Słownik kampanii jako podpowiedź dla Whispera (Whisper sam przytnie zbyt długą listę)."""
    if not WHISPER_NAME_HINTS:
        return None
    names = session.campaign.all_names()
    return ", ".join(names) if names else None


def transcribe_sessions(sessions: list[Session]) -> bool:
    """Transkrybuje sesje, które mają nagranie, ale nie mają jeszcze transkrypcji."""
    print("\n--- Transkrypcja plików audio (z rozpoznawaniem osób) ---")
    os.makedirs(TXT_DIR, exist_ok=True)

    pending = [s for s in sessions if s.audio_path and not s.has_transcript]
    if not pending:
        print("Wszystkie nagrania mają już gotowe transkrypcje!")
        return False

    progress.report("ładowanie modeli")
    print(f"Ładowanie modeli Whisper ({MODEL_SIZE}, {WHISPER_CPU_THREADS} wątków) oraz PyAnnote...")
    whisper_model = load_whisper()
    diarization_pipeline = load_diarization()

    processed_any = False
    embedding_model = None
    for session in pending:
        filename = os.path.basename(session.audio_path)
        print(f"\n[PRZETWARZANIE] {filename}...")
        if not has_duration_header(session.audio_path):
            print(f"[BŁĄD] {filename} nie ma zapisanej długości (częste przy nagraniach z dyktafonów), "
                  "więc rozpoznawanie głosów go nie odczyta. Przytnij nagranie - to zapisze plik od nowa: "
                  f"rpg-chronicler trim {session.name} (albo w GUI: Wykryj ciszę → Przytnij).")
            continue
        try:
            # 1. Wykrywanie głosów (Diarization)
            print("Analizowanie głosów uczestników...")
            started = time.perf_counter()
            progress.report("rozpoznawanie głosów", session.name)
            turns = diarize(diarization_pipeline, session.audio_path, session.name)
            diarization_time = time.perf_counter() - started
            print(f"[CZAS] Rozpoznawanie głosów: {format_duration(diarization_time)}")

            # 2. Transkrypcja tekstu (Whisper)
            print("Transkrypcja mowy...")
            started = time.perf_counter()
            progress.report("transkrypcja", session.name)
            hints = name_hints(session)
            if hints:
                print(f"[INFO] Podpowiedź nazw z kampanii {session.campaign.key}: {hints[:120]}"
                      + ("…" if len(hints) > 120 else ""))
            segments, info = transcribe_audio(whisper_model, session.audio_path, session_name=session.name,
                                              hotwords=hints)
            transcription_time = time.perf_counter() - started
            print(f"[CZAS] Transkrypcja: {format_duration(transcription_time)} "
                  f"(nagranie: {format_duration(info.duration)})")

            # 3. Dopasowywanie tekstu do konkretnego mówcy
            speakers = assign_speakers(segments, turns)

            transcript = Transcript(
                segments=[Segment(round(seg.start, 2), round(seg.end, 2), seg.text.strip(), speaker)
                          for seg, speaker in zip(segments, speakers)],
                audio=filename,
                language=info.language,
                model=MODEL_SIZE,
                duration=round(info.duration, 2),
            )
            save_transcript(transcript, session.json_path, session.txt_path)

            print(f"[SUKCES] Zapisano w: {session.json_path} (oraz .txt)")
            processed_any = True
        except Exception as e:
            print(f"[BŁĄD] Nie udało się przetworzyć {filename}: {e}")
            continue

        # 4. Odciski głosu mówców - do rozpoznawania graczy w kolejnych sesjach
        try:
            from .voiceprints import compute_voiceprints, load_embedding_model
            if embedding_model is None:
                embedding_model = load_embedding_model()
            voiceprints = compute_voiceprints(embedding_model, session.audio_path, transcript, session.name)
            save_voiceprints(voices_path(session), voiceprints)
            print(f"[SUKCES] Odciski głosu {len(voiceprints)} mówców zapisane.")
        except Exception as e:  # transkrypcja jest już zapisana - odciski można policzyć później (voices)
            print(f"[OSTRZEŻENIE] Nie udało się policzyć odcisków głosu {filename}: {e} "
                  f"(spróbuj: rpg-chronicler voices {session.name})")

    return processed_any
