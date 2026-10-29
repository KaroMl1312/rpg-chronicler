import glob
import os

from faster_whisper import WhisperModel
from pyannote.audio import Pipeline

from ..config import AUDIO_DIR, HUGGINGFACE_TOKEN, MODEL_SIZE, SUPPORTED_EXTS, TXT_DIR
from .merge import Turn, assign_speakers


def find_pending_files() -> list[tuple[str, str]]:
    """Zwraca pary (audio, txt) dla nagrań, które nie mają jeszcze transkrypcji."""
    audio_files = []
    for ext in SUPPORTED_EXTS:
        audio_files.extend(glob.glob(os.path.join(AUDIO_DIR, f"*{ext}")))

    pending_files = []
    for audio_path in sorted(audio_files):
        base_name, _ = os.path.splitext(os.path.basename(audio_path))
        txt_path = os.path.join(TXT_DIR, f"{base_name}.txt")
        if not os.path.exists(txt_path):
            pending_files.append((audio_path, txt_path))
    return pending_files


def transcribe_new_files():
    print("\n--- [2/4] Sprawdzanie i transkrypcja plików audio (z rozpoznawaniem osób) ---")
    os.makedirs(TXT_DIR, exist_ok=True)

    if not any(glob.glob(os.path.join(AUDIO_DIR, f"*{ext}")) for ext in SUPPORTED_EXTS):
        print(f"Brak plików audio w katalogu: {AUDIO_DIR}")
        return False

    pending_files = find_pending_files()
    if not pending_files:
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
    for audio_path, txt_path in pending_files:
        filename = os.path.basename(audio_path)
        print(f"\n[PRZETWARZANIE] {filename}...")
        try:
            # 1. Wykrywanie głosów (Diarization)
            print("Analizowanie głosów uczestników...")
            diarization = diarization_pipeline(audio_path)
            turns = [Turn(turn.start, turn.end, spk)
                     for turn, _, spk in diarization.speaker_diarization.itertracks(yield_label=True)]

            # 2. Transkrypcja tekstu (Whisper)
            print("Transkrypcja mowy...")
            segments, info = whisper_model.transcribe(audio_path, language="pl")
            segments = list(segments)  # Konwersja na listę

            # 3. Dopasowywanie tekstu do konkretnego mówcy
            total_minutes = int(info.duration // 60)
            print(f"Długość nagrania: ~{total_minutes} min. Łączenie tekstu z głosami...")
            speakers = assign_speakers(segments, turns)

            # Zapis do pliku tymczasowego, żeby przerwany zapis nie zostawił niepełnej transkrypcji
            tmp_path = txt_path + ".part"
            with open(tmp_path, "w", encoding="utf-8") as f:
                for segment, speaker in zip(segments, speakers):
                    f.write(f"[{speaker}] [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}\n")
            os.replace(tmp_path, txt_path)

            print(f"[SUKCES] Zapisano w: {txt_path}")
            processed_any = True
        except Exception as e:
            print(f"[BŁĄD] Nie udało się przetworzyć {filename}: {e}")

    return processed_any
