"""Model transkrypcji (segmenty z czasami i mówcami), zapis do JSON/.txt i mapowania mówców."""
import json
import os
import re
from dataclasses import asdict, dataclass, field

FORMAT_VERSION = 1

# Formaty linii .txt:
#   [SPEAKER_00] [12.34s -> 15.67s] tekst   (z rozpoznawaniem mówców)
#   [12.34s -> 15.67s] tekst                (starsze transkrypcje bez mówców)
LINE_RE = re.compile(
    r"^(?:\[(?P<speaker>[^\]]+)\] )?\[(?P<start>[\d.]+)s -> (?P<end>[\d.]+)s\]\s*(?P<text>.*)$"
)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None  # None = transkrypcja bez rozpoznawania mówców


@dataclass
class Transcript:
    segments: list[Segment]
    audio: str | None = None
    language: str | None = None
    model: str | None = None
    duration: float | None = None
    version: int = field(default=FORMAT_VERSION)

    # --- serializacja ---

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        data = dict(data)
        segments = [Segment(**s) for s in data.pop("segments")]
        return cls(segments=segments, **data)

    def to_txt(self) -> str:
        lines = []
        for s in self.segments:
            prefix = f"[{s.speaker}] " if s.speaker else ""
            lines.append(f"{prefix}[{s.start:.2f}s -> {s.end:.2f}s] {s.text}")
        return "".join(line + "\n" for line in lines)

    @classmethod
    def from_txt(cls, text: str) -> "Transcript":
        """Parsuje transkrypcję .txt (oba formaty). Linie bez znacznika czasu dokleja do poprzedniego segmentu."""
        segments: list[Segment] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = LINE_RE.match(line)
            if match:
                segments.append(Segment(float(match["start"]), float(match["end"]),
                                        match["text"].strip(), match["speaker"]))
            elif segments:
                segments[-1].text = f"{segments[-1].text} {line}".strip()
        return cls(segments=segments)

    # --- dane dla LLM ---

    @property
    def speakers(self) -> list[str]:
        """Etykiety mówców wykryte przez diaryzację (bez SPEAKER_UNKNOWN)."""
        return sorted({s.speaker for s in self.segments if s.speaker and re.fullmatch(r"SPEAKER_\d+", s.speaker)})

    def compact_for_llm(self, mapping: dict[str, str] | None = None) -> str:
        """Tekst bez znaczników czasu: kolejne wypowiedzi tego samego mówcy sklejone, z imionami z mapowania.

        Model nie potrzebuje czasów do podsumowania, a ich usunięcie mocno zmniejsza liczbę tokenów.
        Transkrypcje bez mówców zostają linia po linii, bez etykiet.
        """
        mapping = mapping or {}
        lines: list[str] = []
        last_speaker = None
        for s in self.segments:
            text = s.text.strip()
            if not text:
                continue
            if s.speaker is None:
                lines.append(text)
                last_speaker = None
                continue
            speaker = mapping.get(s.speaker, s.speaker)
            if speaker == last_speaker:
                lines[-1] += " " + text
            else:
                lines.append(f"{speaker}: {text}")
                last_speaker = speaker
        return "\n".join(lines)


def _write_atomic(path: str, content: str) -> None:
    """Zapis przez plik tymczasowy, żeby przerwany zapis nie zostawił niepełnego pliku."""
    tmp_path = path + ".part"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)


def save_transcript(transcript: Transcript, json_path: str, txt_path: str) -> None:
    """Zapisuje JSON (źródło prawdy) i wygenerowaną z niego wersję .txt do czytania."""
    _write_atomic(txt_path, transcript.to_txt())
    _write_atomic(json_path, json.dumps(transcript.to_dict(), ensure_ascii=False, indent=1))


def load_transcript(json_path: str, txt_path: str) -> Transcript:
    """Wczytuje transkrypcję z JSON, a dla starszych sesji (tylko .txt) parsuje plik tekstowy."""
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return Transcript.from_dict(json.load(f))
    with open(txt_path, "r", encoding="utf-8") as f:
        return Transcript.from_txt(f.read())


def speakers_json_path(txt_path: str) -> str:
    return os.path.splitext(txt_path)[0] + ".mowcy.json"


def load_speaker_mapping(txt_path: str) -> dict[str, str]:
    path = speakers_json_path(txt_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"[OSTRZEŻENIE] Nie udało się wczytać zapisanych mówców: {e}")
        return {}


def save_speaker_mapping(txt_path: str, mapping: dict[str, str]) -> None:
    with open(speakers_json_path(txt_path), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
