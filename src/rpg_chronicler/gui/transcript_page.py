"""Zakładka „Transkrypcja”: tekst z kolorami mówców, a przed transkrypcją - panel nagrania (cisza, przycinanie)."""
from typing import Callable

from gi.repository import Adw, Gtk, Pango

from .. import quality
from ..session import Session
from ..transcript import Transcript, load_speaker_mapping
from .player import SnippetPlayer
from .recording_page import RecordingPanel
from .text import format_minutes, format_timestamp, transcript_blocks
from .widgets import RegisterTaskButton, issues_button, text_page

SPEAKER_COLORS = ["#3584e4", "#e66100", "#26a269", "#9141ac", "#c64600", "#1c71d8", "#a51d2d", "#865e3c"]


class TranscriptPage(Adw.Bin):
    def __init__(self, player: SnippetPlayer, start_task: Callable[[str, list[str]], None],
                 register_task_button: RegisterTaskButton):
        super().__init__()
        self._player = player
        self._start_task = start_task
        self._register = register_task_button
        self._busy = False
        self.recording_panel: RecordingPanel | None = None

    def show_session(self, session: Session, transcript: Transcript | None) -> None:
        self.recording_panel = None
        self.set_child(self._view(session, transcript))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if self.recording_panel is not None:
            self.recording_panel.set_busy(busy)

    def _view(self, session: Session, transcript: Transcript | None) -> Gtk.Widget:
        if transcript is None:
            if session.audio_path:
                self.recording_panel = RecordingPanel(session, self._player, self._start_task,
                                                      self._register, self._busy)
                return self.recording_panel
            return Adw.StatusPage(icon_name="text-x-generic-symbolic", title="Brak transkrypcji",
                                  description="Brak lokalnego nagrania - pobierz je z Google Drive.")

        mapping = load_speaker_mapping(session.txt_path)
        buffer = Gtk.TextBuffer()
        time_tag = buffer.create_tag("time", foreground="#8a8a8a", scale=0.85)
        speaker_tags = {}
        for index, spk in enumerate(transcript.speakers):
            name = mapping.get(spk, spk)
            speaker_tags[name] = buffer.create_tag(None, weight=Pango.Weight.BOLD,
                                                   foreground=SPEAKER_COLORS[index % len(SPEAKER_COLORS)])
        bold = buffer.create_tag("bold", weight=Pango.Weight.BOLD)

        end = buffer.get_end_iter()
        for start, speaker, text in transcript_blocks(transcript, mapping):
            buffer.insert_with_tags(end, f"{format_timestamp(start)}  ", time_tag)
            if speaker:
                buffer.insert_with_tags(end, f"{speaker}: ", speaker_tags.get(speaker, bold))
            buffer.insert(end, text + "\n")

        info = []
        duration = transcript.duration or (transcript.segments[-1].end if transcript.segments else 0)
        if duration:
            info.append(f"nagranie {format_minutes(duration)}")
        info.append(f"{len(transcript.segments)} segmentów")
        if transcript.speakers:
            info.append(f"{len(transcript.speakers)} mówców")
        if not session.has_json:
            info.append("starszy format .txt")
        issues = quality.check(transcript)
        return text_page(buffer, " · ".join(info), leading=issues_button(issues) if issues else None)
