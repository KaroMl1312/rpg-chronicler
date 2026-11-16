"""Zakładka „Transkrypcja”: tekst z kolorami mówców, a przed transkrypcją - panel nagrania (cisza, przycinanie).

Sesja bez nagrania pokazuje tu notatki MG (z przyciskiem edycji).
"""
from typing import Callable

from gi.repository import Adw, Gtk, Pango

from .. import notes, quality, stats
from ..session import Session
from ..transcript import Transcript, load_speaker_mapping
from .player import SnippetPlayer
from .recording_page import RecordingPanel
from .text import format_minutes, format_timestamp, transcript_blocks
from .widgets import RegisterTaskButton, issues_button, markdown_buffer, stats_button, text_page

SPEAKER_COLORS = ["#3584e4", "#e66100", "#26a269", "#9141ac", "#c64600", "#1c71d8", "#a51d2d", "#865e3c"]


class TranscriptPage(Adw.Bin):
    def __init__(self, player: SnippetPlayer, start_task: Callable[[str, list[str]], None],
                 register_task_button: RegisterTaskButton, edit_notes: Callable[[Session], None]):
        super().__init__()
        self._edit_notes = edit_notes
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
        if transcript is None and session.has_notes:
            return self._notes_view(session)
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
        leading = self._issues_widget(session, issues)
        buttons = []
        if transcript.segments:
            buttons.append(stats_button(stats.session_stats(transcript, mapping, session.campaign)))
        return text_page(buffer, " · ".join(info), buttons, leading=leading)

    def _notes_view(self, session: Session) -> Gtk.Widget:
        """Notatki MG sesji bez nagrania: obecni, tekst i „Edytuj notatki…”."""
        session_notes = notes.read_notes(session) or notes.Notes("")
        info = ["sesja bez nagrania · notatki MG"]
        if session_notes.present:
            info.append("obecni: " + ", ".join(session_notes.present))
        leading = None
        if session.has_summary and notes.chronicle_is_stale(session):
            leading = Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["warning"],
                                tooltip_text="Notatki zmieniono po napisaniu kroniki - wygeneruj ją ponownie "
                                             "(Kronika → ⋯ → Generuj ponownie).")
        edit = Gtk.Button(label="Edytuj notatki…", tooltip_text="Popraw notatki albo listę obecnych postaci")
        edit.connect("clicked", lambda _b: self._edit_notes(session))
        return text_page(markdown_buffer(session_notes.text), " · ".join(info), [edit], leading=leading)

    def _issues_widget(self, session: Session, issues: list[quality.Issue]) -> Gtk.Widget | None:
        """Uwagi jakości (z „Usuń powtórzenia” przy pętlach Whispera) albo „Przywróć” po ich usunięciu."""
        def task_button(label: str, title: str, args: list[str], tooltip: str) -> Gtk.Button:
            button = Gtk.Button(label=label, tooltip_text=tooltip)
            button.connect("clicked", lambda _b: self._start_task(title, args))
            self._register(button)
            return button

        undo = None
        if quality.backups(session):
            undo = task_button("Przywróć sprzed usunięcia powtórzeń", f"Przywracanie transkrypcji {session.name}",
                               ["fix-loops", session.name, "--undo"],
                               "Wróć do transkrypcji sprzed ostatniego usunięcia powtórzeń Whispera")
        if issues:
            actions = []
            if any(i.kind == "petla" for i in issues):
                actions.append(task_button("Usuń powtórzenia", f"Usuwanie powtórzeń {session.name}",
                                           ["fix-loops", session.name],
                                           "Z każdego ciągu zostaje pierwsza wypowiedź; kopia do cofnięcia zostaje"))
            return issues_button(issues, actions + ([undo] if undo else []))
        if undo is not None:
            undo.set_label("")
            undo.set_icon_name("edit-undo-symbolic")
            undo.add_css_class("flat")
        return undo
