"""Statystyki sesji z transkrypcji: kto ile mówił, MG a gracze, czas gry i przerw.

Liczone z segmentów Whispera i mapowania mówców (bez AI, bez nagrania). Czas mówienia = suma długości
segmentów mówcy; wypowiedź = ciąg kolejnych segmentów tego samego mówcy. Przerwa = co najmniej
BREAK_SECONDS bez żadnej wypowiedzi (cisza przed pierwszą i po ostatniej wypowiedzi się nie liczy).
Tylko stdlib (używane też przez GUI).
"""
from dataclasses import dataclass, field

from .campaigns import Campaign
from .transcript import Transcript

BREAK_SECONDS = 3 * 60    # w nagraniach użytkownika zwykłe pauzy w grze są krótsze niż 3 min
GAME_MASTER = "MG"        # jak voices.GAME_MASTER (bez importu - voices ciągnie listę sesji)
UNKNOWN = "nierozpoznany"  # SPEAKER_UNKNOWN i segmenty bez mówcy


@dataclass
class SpeakerStats:
    name: str
    seconds: float = 0.0
    utterances: int = 0
    words: int = 0


@dataclass
class SessionStats:
    duration: float                     # długość nagrania (albo do końca ostatniej wypowiedzi)
    first: float                        # początek pierwszej wypowiedzi
    last: float                         # koniec ostatniej wypowiedzi
    speakers: list[SpeakerStats] = field(default_factory=list)   # od najdłużej mówiącego
    breaks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def speech_seconds(self) -> float:
        return sum(s.seconds for s in self.speakers)

    @property
    def break_seconds(self) -> float:
        return sum(end - start for start, end in self.breaks)

    @property
    def play_seconds(self) -> float:
        """Od pierwszej do ostatniej wypowiedzi, bez przerw."""
        return max(0.0, self.last - self.first - self.break_seconds)

    @property
    def gm_seconds(self) -> float:
        return sum(s.seconds for s in self.speakers if s.name == GAME_MASTER)

    @property
    def players(self) -> list[SpeakerStats]:
        """Nazwani mówcy poza MG (bez etykiet SPEAKER_XX)."""
        return [s for s in self.speakers if s.name not in (GAME_MASTER, UNKNOWN) and not s.name.startswith("SPEAKER_")]

    def share(self, seconds: float) -> float:
        return seconds / self.speech_seconds if self.speech_seconds else 0.0


def _resolver(campaign: Campaign | None):
    if campaign is None:
        return lambda name: name
    from .voices import NameResolver  # import tutaj: voices jest cięższe, a resolver opcjonalny
    resolver = NameResolver(campaign)
    return lambda name: resolver.resolve(name)


def session_stats(transcript: Transcript, mapping: dict[str, str] | None = None,
                  campaign: Campaign | None = None) -> SessionStats:
    """Statystyki transkrypcji; imiona z mapowania (z kampanią: ujednolicone, gracz → jego postać)."""
    mapping = mapping or {}
    resolve = _resolver(campaign)
    segments = [s for s in transcript.segments if s.text.strip()]
    speakers: dict[str, SpeakerStats] = {}
    breaks: list[tuple[float, float]] = []
    previous_name, previous_end = None, None
    for s in segments:
        label = s.speaker or "SPEAKER_UNKNOWN"
        name = mapping.get(label, label).strip() or label
        name = resolve(name) if name != label else (UNKNOWN if label == "SPEAKER_UNKNOWN" else label)
        stats = speakers.setdefault(name, SpeakerStats(name))
        stats.seconds += max(0.0, s.end - s.start)
        stats.words += len(s.text.split())
        if name != previous_name:
            stats.utterances += 1
        if previous_end is not None and s.start - previous_end >= BREAK_SECONDS:
            breaks.append((previous_end, s.start))
            stats.utterances += name == previous_name   # po przerwie to nowa wypowiedź
        previous_name = name
        previous_end = max(previous_end or 0.0, s.end)
    first = segments[0].start if segments else 0.0
    last = previous_end or 0.0
    duration = transcript.duration or last
    ordered = sorted(speakers.values(), key=lambda s: s.seconds, reverse=True)
    return SessionStats(duration, first, last, ordered, breaks)


def merge_stats(all_stats: list[SessionStats]) -> SessionStats:
    """Suma kilku sesji (np. całej kampanii): mówcy po imieniu, przerwy i czas gry dodane."""
    speakers: dict[str, SpeakerStats] = {}
    for stats in all_stats:
        for s in stats.speakers:
            total = speakers.setdefault(s.name, SpeakerStats(s.name))
            total.seconds += s.seconds
            total.utterances += s.utterances
            total.words += s.words
    # Sesje sklejone jedna za drugą: czas od pierwszej do ostatniej wypowiedzi = suma takich czasów
    span = sum(s.last - s.first for s in all_stats)
    breaks = [b for s in all_stats for b in s.breaks]
    ordered = sorted(speakers.values(), key=lambda s: s.seconds, reverse=True)
    return SessionStats(sum(s.duration for s in all_stats), 0.0, span, ordered, breaks)


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def breaks_text(stats: SessionStats) -> str:
    if not stats.breaks:
        return f"bez przerw (≥ {BREAK_SECONDS // 60} min ciszy)"
    count = len(stats.breaks)
    noun = "przerwa" if count == 1 else "przerwy" if 2 <= count % 10 <= 4 and count // 10 % 10 != 1 else "przerw"
    return f"{count} {noun}, razem {format_duration(stats.break_seconds)}"


def format_report(stats: SessionStats) -> str:
    """Tabelka do terminala."""
    lines = [f"Nagranie {format_duration(stats.duration)}, gra {format_duration(stats.play_seconds)}, "
             + breaks_text(stats)]
    if stats.gm_seconds:
        players = sum(s.seconds for s in stats.players)
        lines.append(f"MG {stats.share(stats.gm_seconds):.0%} · gracze {stats.share(players):.0%} czasu mówienia")
    width = max([len(s.name) for s in stats.speakers] + [5])
    lines.append(f"  {'Mówca':<{width}}  {'czas':>10}  {'udział':>6}  {'wypowiedzi':>10}  {'słowa':>7}")
    for s in stats.speakers:
        lines.append(f"  {s.name:<{width}}  {format_duration(s.seconds):>10}  {stats.share(s.seconds):>6.0%}  "
                     f"{s.utterances:>10}  {s.words:>7}")
    return "\n".join(lines)
