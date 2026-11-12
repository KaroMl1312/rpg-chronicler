"""Zakładka „Kronika”: kronika albo jej skrót (przełącznik), PDF, Discord, ponowne generowanie."""
from typing import Callable

from gi.repository import Adw, Gio, Gtk

from .. import chronicle
from ..session import Session
from .widgets import RegisterTaskButton, markdown_buffer, task_button, text_page, text_view


class ChroniclePage(Adw.Bin):
    def __init__(self, *, summarize: Callable[[Session, bool], None], write_brief: Callable[[Session, bool], None],
                 open_pdf: Callable[[Session], None], show_discord: Callable[[Session], None],
                 provider_label: Callable[[], str], register_task_button: RegisterTaskButton):
        super().__init__()
        self._summarize = summarize
        self._write_brief = write_brief
        self._open_pdf = open_pdf
        self._show_discord = show_discord
        self._provider_label = provider_label
        self._register = register_task_button
        self._mode = "kronika"  # przełącznik „Kronika / Skrót” - pamiętany między sesjami

    def show_session(self, session: Session) -> None:
        self.set_child(self._view(session))

    def _view(self, session: Session) -> Gtk.Widget:
        if not session.has_summary:
            status = Adw.StatusPage(icon_name="x-office-document-symbolic", title="Brak kroniki")
            if session.has_transcript:
                status.set_description(f"AI ({self._provider_label()}) napisze kronikę sesji w klimacie "
                                       f"systemu {session.system_name}.")
                status.set_child(task_button("Generuj kronikę", lambda: self._summarize(session, False),
                                             self._register))
            else:
                status.set_description("Kronikę można wygenerować po transkrypcji nagrania.")
            return status

        try:
            with open(session.summary_path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return Adw.StatusPage(icon_name="dialog-information-symbolic", title="Nie można odczytać kroniki",
                                  description=str(e))

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        stack.add_named(text_view(markdown_buffer(content)), "kronika")
        stack.add_named(self._brief_view(session), "skrot")
        stack.set_visible_child_name(self._mode)

        toggles = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        toggles.add(Adw.Toggle(label="Kronika", name="kronika"))
        toggles.add(Adw.Toggle(label="Skrót", name="skrot",
                               tooltip="Najważniejsze wydarzenia w jednym akapicie"))
        toggles.set_active_name(self._mode)

        def toggled(group, _pspec):
            self._mode = group.get_active_name()
            stack.set_visible_child_name(self._mode)

        toggles.connect("notify::active-name", toggled)

        regenerate = Gtk.Button(label="Generuj ponownie")
        regenerate.connect("clicked", lambda _b: self._summarize(session, True))
        open_button = Gtk.Button(label="Otwórz w edytorze")
        open_button.connect("clicked", lambda _b: Gtk.FileLauncher.new(
            Gio.File.new_for_path(session.summary_path)).launch(self.get_root(), None, None))
        pdf_button = Gtk.Button(label="PDF", tooltip_text="Otwórz kronikę jako PDF (utworzy go, jeśli trzeba)")
        pdf_button.connect("clicked", lambda _b: self._open_pdf(session))
        discord_button = Gtk.Button(label="Wyślij na Discord")
        discord_button.connect("clicked", lambda _b: self._show_discord(session))
        for button in (regenerate, pdf_button, discord_button):
            self._register(button)
        sent = chronicle.sent_text(session)
        info = f"{session.system_name} · " + (f"wysłano na Discord {sent}" if sent
                                               else f"{self._provider_label()} przy ponownym generowaniu")
        return text_page(stack, info, [open_button, pdf_button, discord_button, regenerate], leading=toggles)

    def _brief_view(self, session: Session) -> Gtk.Widget:
        """Skrót kroniki (jeden akapit) albo zachęta do jego napisania."""
        brief = chronicle.read_brief(session)
        if not brief:
            status = Adw.StatusPage(icon_name="view-list-bullet-symbolic", title="Brak skrótu",
                                    description="AI przeczyta kronikę i opowie w jednym akapicie, co najważniejszego "
                                                "się wydarzyło - bez zbędnych szczegółów. Trwa to kilkanaście sekund.")
            status.set_child(task_button("Napisz skrót", lambda: self._write_brief(session, False), self._register))
            return status

        current = chronicle.brief_is_current(session)
        label = Gtk.Label(label="Skrót kroniki" if current else "Skrót jest starszy niż kronika - napisz go ponownie",
                          xalign=0, hexpand=True, wrap=True)
        label.add_css_class("dim-label" if current else "warning")
        again = Gtk.Button(label="Napisz ponownie", valign=Gtk.Align.CENTER)
        again.add_css_class("flat" if current else "suggested-action")
        again.connect("clicked", lambda _b: self._write_brief(session, True))
        self._register(again)
        bar = Gtk.Box(spacing=6, margin_top=10, margin_start=24, margin_end=12)
        bar.append(label)
        bar.append(again)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(text_view(markdown_buffer(brief)))
        return box
