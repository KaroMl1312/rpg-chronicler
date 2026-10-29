"""Operacje na plikach transkrypcji (.txt) i mapowaniach mówców (.mowcy.json)."""
import json
import os
import re

# Format linii: [SPEAKER_00] [12.34s -> 15.67s] tekst
LINE_RE = re.compile(r"^\[(?P<speaker>[^\]]+)\] \[[\d.]+s -> [\d.]+s\]\s*(?P<text>.*)$")


def detect_speakers(transcript_text: str) -> list[str]:
    return sorted(set(re.findall(r"\[(SPEAKER_\d+)\]", transcript_text)))


def compact_for_llm(transcript_text: str, mapping: dict[str, str] | None = None) -> str:
    """Usuwa znaczniki czasu, łączy kolejne wypowiedzi tego samego mówcy i podstawia imiona.

    Model nie potrzebuje czasów do podsumowania, a ich usunięcie mocno zmniejsza liczbę tokenów.
    """
    mapping = mapping or {}
    lines: list[str] = []
    last_speaker = None
    for raw_line in transcript_text.splitlines():
        match = LINE_RE.match(raw_line.strip())
        if not match:
            if raw_line.strip():
                lines.append(raw_line.strip())
                last_speaker = None
            continue

        text = match["text"].strip()
        if not text:
            continue
        speaker = mapping.get(match["speaker"], match["speaker"])
        if speaker == last_speaker:
            lines[-1] += " " + text
        else:
            lines.append(f"{speaker}: {text}")
            last_speaker = speaker
    return "\n".join(lines)


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
