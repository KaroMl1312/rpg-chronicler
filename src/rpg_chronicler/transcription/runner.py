import os

from faster_whisper import WhisperModel
from pyannote.audio import Pipeline
from tqdm import tqdm

from ..config import HUGGINGFACE_TOKEN, MODEL_SIZE, TXT_DIR
from ..session import Session
from .merge import Turn, assign_speakers


def transcribe_sessions(sessions: list[Session]) -> bool:
    """Transkrybuje sesje, które mają nagranie, ale nie mają jeszcze transkrypcji."""
    print("\n--- Transkrypcja plików audio (z rozpoznawaniem osób) ---")
    os.makedirs(TXT_DIR, exist_ok=True)

    pending = [s for s in sessions if s.audio_path and not s.has_transcript]
    if not pending:
        print("Wszystkie nagrania mają już gotowe transkrypcje!")
        return False

    print("Ładowanie modeli Whisper oraz PyAnnote...")
    whisper_model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    # Ładowanie modelu do rozróżniania głosów
    diarization_pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=HUGGINGFACE_TOKEN
    )
    processed_any = False
    for session in pending:
        filename = os.path.basename(session.audio_path)
        print(f"\n[PRZETWARZANIE] {filename}...")
        try:
            # 1. Wykrywanie głosów (Diarization)
            print("Analizowanie głosów uczestników...")
            diarization = diarization_pipeline(session.audio_path)
            turns = [Turn(turn.start, turn.end, spk)
                     for turn, _, spk in diarization.speaker_diarization.itertracks(yield_label=True)]

            # 2. Transkrypcja tekstu (Whisper) - segmenty powstają w trakcie iterowania
            print("Transkrypcja mowy...")
            segments_iter, info = whisper_model.transcribe(session.audio_path, language="pl")
            segments = []
            with tqdm(total=round(info.duration), unit="s", desc="Transkrypcja") as progress:
                for segment in segments_iter:
                    segments.append(segment)
                    progress.update(max(0, min(round(segment.end), progress.total) - progress.n))

            # 3. Dopasowywanie tekstu do konkretnego mówcy
            speakers = assign_speakers(segments, turns)

            # Zapis do pliku tymczasowego, żeby przerwany zapis nie zostawił niepełnej transkrypcji
            tmp_path = session.txt_path + ".part"
            with open(tmp_path, "w", encoding="utf-8") as f:
                for segment, speaker in zip(segments, speakers):
                    f.write(f"[{speaker}] [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}\n")
            os.replace(tmp_path, session.txt_path)

            print(f"[SUKCES] Zapisano w: {session.txt_path}")
            processed_any = True
        except Exception as e:
            print(f"[BŁĄD] Nie udało się przetworzyć {filename}: {e}")

    return processed_any
