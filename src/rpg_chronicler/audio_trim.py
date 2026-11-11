"""Wykrywanie ciszy w nagraniu i przycinanie go (ffmpeg). Tylko biblioteka standardowa - używa tego też GUI.

Przycinanie zachowuje jakość:
- AAC/MP3: kopiowanie strumienia bez kodowania (demuxer concat z inpoint/outpoint),
- formaty bezstratne (FLAC, PCM, ALAC): filtr aselect i kodowanie tym samym kodekiem (bezstratnie),
- inne (Vorbis, Opus): filtr aselect i ponowne kodowanie z wysoką jakością.
Oryginał trafia do podfolderu `oryginaly/` obok nagrania (list_sessions go nie widzi).
"""
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import progress

DEFAULT_NOISE_DB = -40.0     # poniżej tej głośności fragment uznajemy za ciszę
DEFAULT_MIN_SILENCE = 30.0   # krótsze przerwy nas nie interesują (sekundy)
DEFAULT_MARGIN = 2.0         # zapas zostawiany przed i po mowie (sekundy)
BACKUP_DIR_NAME = "oryginaly"

COPY_CODECS = {"aac", "mp3"}
LOSSLESS_CODECS = {"flac", "alac"}  # oraz pcm_*
REENCODE_CODECS = {"vorbis": ["-c:a", "libvorbis", "-q:a", "7"], "opus": ["-c:a", "libopus", "-b:a", "160k"]}

SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")
OUT_TIME_RE = re.compile(r"^out_time_us=(\d+)")


class TrimError(Exception):
    pass


@dataclass
class SilenceAnalysis:
    audio: str                       # nazwa pliku nagrania
    size: int                        # rozmiar i czas modyfikacji - do sprawdzania, czy analiza jest aktualna
    mtime: float
    duration: float
    noise_db: float = DEFAULT_NOISE_DB
    min_silence: float = DEFAULT_MIN_SILENCE
    silences: list[tuple[float, float]] = field(default_factory=list)

    @property
    def silence_total(self) -> float:
        return sum(end - start for start, end in self.silences)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SilenceAnalysis":
        data = dict(data)
        data["silences"] = [tuple(s) for s in data.get("silences", [])]
        return cls(**data)


# --- czas ---

def parse_timestamp(text: str) -> float:
    """'1:20:05', '80:05', '4805' lub '4805.5' -> sekundy. Rzuca ValueError przy błędnym formacie."""
    text = text.strip().replace(",", ".")
    parts = text.split(":")
    if not text or len(parts) > 3 or any(not re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"Niepoprawny czas: '{text}' (użyj gg:mm:ss)")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    if len(parts) > 1 and any(float(p) >= 60 for p in parts[1:]):
        raise ValueError(f"Niepoprawny czas: '{text}' (minuty i sekundy muszą być < 60)")
    return seconds


def format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


# --- ffmpeg ---

def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise TrimError(f"Brak programu {', '.join(missing)} - zainstaluj: sudo dnf install ffmpeg")


def probe(path: str) -> tuple[float, str]:
    """(długość w sekundach, kodek pierwszego strumienia audio)."""
    require_ffmpeg()
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "format=duration:stream=codec_name", "-of", "json", path],
        capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
        codec = data["streams"][0]["codec_name"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        details = proc.stderr.strip() or "brak strumienia audio"
        raise TrimError(f"Nie można odczytać nagrania {os.path.basename(path)}: {details}")
    try:
        return float(data["format"]["duration"]), codec
    except (KeyError, TypeError, ValueError):
        # Np. FLAC nagrany strumieniowo (dyktafon, aplikacja) nie ma długości w nagłówku - mierzymy dekodując
        return decoded_duration(path), codec


def decoded_duration(path: str) -> float:
    """Długość nagrania zmierzona przez zdekodowanie całości (kilka sekund nawet dla wielu godzin)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:1", "-i", path,
         "-map", "0:a", "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    times = [int(m[1]) for line in proc.stdout.splitlines() if (m := OUT_TIME_RE.match(line))]
    if proc.returncode != 0 or not times or times[-1] <= 0:
        details = proc.stderr.strip().splitlines()[-1:] or ["nieznany błąd"]
        raise TrimError(f"Nie można zmierzyć długości nagrania {os.path.basename(path)}: {details[0]}")
    return times[-1] / 1e6


_header_cache: dict[tuple[str, int, float], bool] = {}


def has_duration_header(path: str) -> bool:
    """Czy plik ma zapisaną długość (bez niej pyannote/torchcodec nie odczyta nagrania).

    Wynik jest zapamiętywany dla danej wersji pliku (ścieżka, rozmiar, data) - GUI pyta o to przy każdym
    wyświetleniu sesji. Bez ffprobe nie da się tego sprawdzić - wtedy zakładamy, że tak.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return False
    key = (os.path.abspath(path), stat.st_size, stat.st_mtime)
    if key in _header_cache:
        return _header_cache[key]
    if shutil.which("ffprobe") is None:
        return True
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                          capture_output=True, text=True)
    try:
        result = float(proc.stdout.strip()) > 0
    except ValueError:
        result = False
    _header_cache[key] = result
    return result


def _run_ffmpeg(args: list[str], stage: str, session_name: str | None, total: float,
                on_line=None) -> None:
    """Uruchamia ffmpeg, raportuje postęp (out_time_us vs `total`) i przekazuje linie stderr do `on_line`."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-progress", "pipe:2", *args]
    tail: list[str] = []
    with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True, errors="replace") as proc:
        try:
            for line in proc.stderr:
                line = line.rstrip()
                match = OUT_TIME_RE.match(line)
                if match:
                    progress.report(stage, session_name, min(int(match[1]) / 1e6, total), total)
                    continue
                if on_line:
                    on_line(line)
                if "=" not in line or " " in line:  # pomijamy pozostałe linie key=value z -progress
                    tail = (tail + [line])[-15:]
            proc.wait()
        except BaseException:
            proc.kill()
            raise
    if proc.returncode != 0:
        raise TrimError("ffmpeg zakończył się błędem:\n" + "\n".join(tail))


# --- wykrywanie ciszy ---

def detect_silences(path: str, session_name: str | None = None, noise_db: float = DEFAULT_NOISE_DB,
                    min_silence: float = DEFAULT_MIN_SILENCE) -> SilenceAnalysis:
    duration, _codec = probe(path)
    silences: list[tuple[float, float]] = []
    open_start: list[float] = []

    def on_line(line: str) -> None:
        if (match := SILENCE_START_RE.search(line)):
            open_start[:] = [max(0.0, float(match[1]))]
        elif (match := SILENCE_END_RE.search(line)) and open_start:
            silences.append((round(open_start[0], 2), round(min(float(match[1]), duration), 2)))
            open_start.clear()

    progress.report("wykrywanie ciszy", session_name)
    _run_ffmpeg(["-i", path, "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                "wykrywanie ciszy", session_name, duration, on_line)
    if open_start:  # cisza do końca pliku, a ffmpeg nie zgłosił jej końca
        silences.append((round(open_start[0], 2), round(duration, 2)))

    stat = os.stat(path)
    return SilenceAnalysis(os.path.basename(path), stat.st_size, stat.st_mtime, round(duration, 2),
                           noise_db, min_silence, silences)


def cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "cisza"


def analysis_path(session_name: str) -> Path:
    return cache_dir() / f"{session_name}.json"


def save_analysis(session_name: str, analysis: SilenceAnalysis) -> None:
    path = analysis_path(session_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis.to_dict(), ensure_ascii=False), encoding="utf-8")


def load_analysis(session_name: str, audio_path: str) -> SilenceAnalysis | None:
    """Zapisana analiza, o ile dotyczy obecnej wersji pliku nagrania (ten sam rozmiar i data)."""
    try:
        analysis = SilenceAnalysis.from_dict(json.loads(analysis_path(session_name).read_text(encoding="utf-8")))
        stat = os.stat(audio_path)
    except (OSError, ValueError, TypeError):
        return None
    if analysis.size != stat.st_size or abs(analysis.mtime - stat.st_mtime) > 1e-3:
        return None
    return analysis


# --- plan przycięcia ---

def suggest_range(analysis: SilenceAnalysis, margin: float = DEFAULT_MARGIN) -> tuple[float, float]:
    """Zakres od końca ciszy na początku nagrania do początku ciszy na jego końcu (z zapasem)."""
    start, end = 0.0, analysis.duration
    for silence_start, silence_end in analysis.silences:
        if silence_start <= 1.0:
            start = max(0.0, silence_end - margin)
        if silence_end >= analysis.duration - 1.0:
            end = min(analysis.duration, silence_start + margin)
    if end <= start:  # całe nagranie to cisza - nie proponujemy cięcia
        return 0.0, analysis.duration
    return round(start, 2), round(end, 2)


def keep_segments(analysis: SilenceAnalysis, start: float, end: float, cut_gaps_minutes: float = 0,
                  margin: float = DEFAULT_MARGIN) -> list[tuple[float, float]]:
    """Fragmenty do zachowania: [start, end] bez przerw dłuższych niż `cut_gaps_minutes` (0 = nie wycinaj)."""
    start, end = max(0.0, start), min(analysis.duration, end)
    if end <= start:
        raise TrimError("Koniec musi być po początku.")
    segments = [(start, end)]
    if cut_gaps_minutes > 0:
        for silence_start, silence_end in analysis.silences:
            cut_start, cut_end = max(silence_start + margin, start), min(silence_end - margin, end)
            if silence_end - silence_start < cut_gaps_minutes * 60 or cut_end - cut_start <= 0:
                continue
            new_segments = []
            for seg_start, seg_end in segments:
                if cut_end <= seg_start or cut_start >= seg_end:
                    new_segments.append((seg_start, seg_end))
                    continue
                if cut_start > seg_start:
                    new_segments.append((seg_start, cut_start))
                if cut_end < seg_end:
                    new_segments.append((cut_end, seg_end))
            segments = new_segments
    return [(round(s, 2), round(e, 2)) for s, e in segments if e - s > 0.05]


def describe_plan(analysis: SilenceAnalysis, segments: list[tuple[float, float]]) -> str:
    kept = sum(e - s for s, e in segments)
    gaps = len(segments) - 1
    text = (f"Zostaje {format_timestamp(kept)} z {format_timestamp(analysis.duration)} "
            f"(od {format_timestamp(segments[0][0])} do {format_timestamp(segments[-1][1])}")
    if gaps:
        text += f", bez {gaps} {'przerwy' if gaps == 1 else 'przerw'} w środku"
    return text + ")."


# --- przycinanie ---

def _encode_args(codec: str) -> list[str]:
    if codec in LOSSLESS_CODECS or codec.startswith("pcm_"):
        return ["-c:a", codec]
    if codec in REENCODE_CODECS:
        return REENCODE_CODECS[codec]
    return []  # domyślny koder dla formatu pliku


def trim_audio(path: str, segments: list[tuple[float, float]], session_name: str | None = None) -> str:
    """Zastępuje nagranie przyciętą wersją; oryginał przenosi do `oryginaly/`. Zwraca ścieżkę kopii oryginału."""
    if not segments:
        raise TrimError("Nie ma nic do zachowania.")
    duration, codec = probe(path)
    expected = sum(e - s for s, e in segments)
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    # Ukryta nazwa (z kropką) - list_sessions nie weźmie niedokończonego pliku za sesję
    tmp_path = os.path.join(folder, f".{stem}.przycinanie{ext}")
    list_path = os.path.join(folder, f".{stem}.przycinanie.txt")

    try:
        if codec in COPY_CODECS:
            escaped = path.replace("'", "'\\''")
            with open(list_path, "w", encoding="utf-8") as f:
                for start, end in segments:
                    f.write(f"file '{escaped}'\ninpoint {start}\noutpoint {end}\n")
            args = ["-y", "-f", "concat", "-safe", "0", "-i", list_path, "-map", "0:a", "-c", "copy", tmp_path]
        else:
            condition = "+".join(f"between(t,{s},{e})" for s, e in segments)
            args = ["-y", "-i", path, "-map", "0:a", "-af", f"aselect='{condition}',asetpts=N/SR/TB",
                    *_encode_args(codec), tmp_path]
        _run_ffmpeg(args, "przycinanie", session_name, expected)

        new_duration, _ = probe(tmp_path)
        if abs(new_duration - expected) > max(3.0, expected * 0.005):
            raise TrimError(f"Przycięte nagranie ma {format_timestamp(new_duration)} zamiast "
                            f"{format_timestamp(expected)} - zostawiam oryginał bez zmian.")

        backup_dir = os.path.join(folder, BACKUP_DIR_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, filename)
        counter = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(backup_dir, f"{stem} ({counter}){ext}")
            counter += 1
        os.replace(path, backup_path)
        os.replace(tmp_path, path)
        return backup_path
    finally:
        for leftover in (tmp_path, list_path):
            if os.path.exists(leftover):
                os.remove(leftover)
