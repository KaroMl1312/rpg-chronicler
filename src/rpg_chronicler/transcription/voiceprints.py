"""Liczenie odcisków głosu mówców (model pyannote/wespeaker) z nagrania i czasów z transkrypcji."""
import os

import numpy as np
from pyannote.audio import Inference, Model
from pyannote.core import Segment

from .. import progress
from ..audio_trim import has_duration_header
from ..config import HUGGINGFACE_TOKEN
from ..session import Session
from ..transcript import Transcript
from ..voices import EMBEDDING_MODEL, Voiceprint, has_voiceprints, save_voiceprints, voices_path

MIN_SEGMENT = 2.0       # krótsze wypowiedzi dają niestabilne odciski
MAX_SEGMENT = 15.0      # z dłuższych bierzemy tylko początek
SPEECH_PER_SPEAKER = 120.0
MIN_SPEECH = 8.0        # mówców z mniejszą ilością mowy pomijamy (szumy, przypadkowe głosy)


def load_embedding_model() -> Inference:
    return Inference(Model.from_pretrained(EMBEDDING_MODEL, token=HUGGINGFACE_TOKEN), window="whole")


def compute_voiceprints(inference: Inference, audio_path: str, transcript: Transcript,
                        session_name: str | None = None) -> dict[str, Voiceprint]:
    """Odcisk każdego mówcy = średnia (ważona długością) odcisków jego najdłuższych wypowiedzi."""
    voiceprints = {}
    speakers = transcript.speakers
    for index, spk in enumerate(speakers):
        progress.report("odciski głosu", session_name, index, len(speakers))
        segments = sorted((s for s in transcript.segments if s.speaker == spk and s.end - s.start >= MIN_SEGMENT),
                          key=lambda s: s.end - s.start, reverse=True)
        chosen, total = [], 0.0
        for segment in segments:
            if total >= SPEECH_PER_SPEAKER:
                break
            chosen.append(segment)
            total += segment.end - segment.start
        if total < MIN_SPEECH:
            continue

        vectors, weights = [], []
        for segment in chosen:
            embedding = np.asarray(inference.crop(audio_path, Segment(segment.start,
                                                                      min(segment.end, segment.start + MAX_SEGMENT))))
            embedding = embedding.reshape(-1)
            norm = np.linalg.norm(embedding)
            if not np.all(np.isfinite(embedding)) or norm == 0:
                continue
            vectors.append(embedding / norm)
            weights.append(segment.end - segment.start)
        if vectors:
            mean = np.average(vectors, axis=0, weights=weights)
            voiceprints[spk] = Voiceprint(tuple((mean / np.linalg.norm(mean)).tolist()), total)
    progress.report("odciski głosu", session_name, len(speakers), len(speakers))
    return voiceprints


def voiceprint_sessions(sessions: list[Session], force: bool = False, inference: Inference | None = None) -> int:
    """Liczy brakujące odciski głosu (sesje z nagraniem i transkrypcją z mówcami). Zwraca liczbę sesji."""
    done = 0
    for session in sessions:
        if not session.audio_path or not session.has_transcript or (has_voiceprints(session) and not force):
            continue
        transcript = session.load_transcript()
        if not transcript.speakers:
            continue
        if not has_duration_header(session.audio_path):
            print(f"[POMINIĘTO] {session.name}: nagranie bez zapisanej długości - przytnij je (trim).")
            continue
        if inference is None:
            print("Ładowanie modelu odcisków głosu...")
            inference = load_embedding_model()
        print(f"[ODCISKI GŁOSU] {session.name}...")
        try:
            voiceprints = compute_voiceprints(inference, session.audio_path, transcript, session.name)
        except Exception as e:  # błąd jednej sesji nie przerywa pozostałych
            print(f"[BŁĄD] {session.name}: {e}")
            continue
        save_voiceprints(voices_path(session), voiceprints)
        print(f"[SUKCES] {session.name}: odciski {len(voiceprints)} mówców -> {os.path.basename(voices_path(session))}")
        done += 1
    return done
