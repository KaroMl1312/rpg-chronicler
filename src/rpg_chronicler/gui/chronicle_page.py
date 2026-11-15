"""Zakładka „Kronika”: kronika albo jej skrót (przełącznik), poprawka poleceniem, PDF, Discord, ponowne generowanie."""
from typing import Callable

from gi.repository import Adw, Gio, Gtk

from .. import chronicle
from ..session import Session
from .widgets import RegisterTaskButton, markdown_buffer, task_button, text_page, text_view


class ChroniclePage(Adw.Bin):
    def __init__(self, *, summarize: Callable[[Session, bool], None], write_brief: Callable[[Session, bool], None],
                 revise: Callable[[Session, str], None], undo_revision: Callable[[Session], None],
                 write_quotes: Callable[[Session, bool], None],
                 open_pdf: Callable[[Session], None], show_discord: Callable[[Session], None],
                 provider_label: Callable[[], str], register_task_button: RegisterTaskButton):
        super().__init__()
        self._revise = revise
        self._write_quotes = write_quotes
        self._undo_revision = undo_revision
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
        stack.add_named(self._quotes_view(session), "cytaty")
        stack.set_visible_child_name(self._mode)

        toggles = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        toggles.add(Adw.Toggle(label="Kronika", name="kronika"))
        toggles.add(Adw.Toggle(label="Skrót", name="skrot",
                               tooltip="Najważniejsze wydarzenia w jednym akapicie"))
        toggles.add(Adw.Toggle(label="Cytaty", name="cytaty", tooltip="Najlepsze cytaty z sesji (PDF, Discord)"))
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
        revise_button = Gtk.Button(label="Popraw…", tooltip_text="Popraw kronikę poleceniem dla AI, "
                                                                 "np. „to nie Hans, tylko Hanna”")
        revise_button.connect("clicked", lambda _b: self._ask_revision(session))
        buttons = [revise_button]
        if chronicle.previous_versions(session):
            undo = Gtk.Button(label="Cofnij poprawkę", tooltip_text="Przywróć wersję sprzed ostatniej poprawki")
            undo.connect("clicked", lambda _b: self._undo_revision(session))
            buttons.append(undo)
        for button in (regenerate, pdf_button, discord_button, *buttons):
            self._register(button)
        sent = chronicle.sent_text(session)
        info = f"{session.system_name} · " + (f"wysłano na Discord {sent}" if sent
                                               else f"{self._provider_label()} przy ponownym generowaniu")
        return text_page(stack, info, [*buttons, open_button, pdf_button, discord_button, regenerate], leading=toggles)

    def _quotes_view(self, session: Session) -> Gtk.Widget:
        """Najlepsze cytaty z sesji albo zachęta do ich wybrania."""
        quotes = chronicle.read_quotes(session)
        if not quotes:
            status = Adw.StatusPage(icon_name="user-available-symbolic", title="Brak cytatów",
                                    description="AI wybierze 3–5 najlepszych wypowiedzi z sesji - zabawnych, "
                                                "dramatycznych albo kluczowych. Trafią na koniec PDF i pod "
                                                "zapowiedź na Discordzie.")
            status.set_child(task_button("Wybierz cytaty", lambda: self._write_quotes(session, False),
                                         self._register))
            return status

        again = Gtk.Button(label="Wybierz ponownie", valign=Gtk.Align.CENTER, css_classes=["flat"])
        again.connect("clicked", lambda _b: self._write_quotes(session, True))
        self._register(again)
        edit = Gtk.Button(label="Edytuj", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text="Otwórz plik cytatów w edytorze (jeden cytat w linii: „cytat” — Postać)")
        edit.connect("clicked", lambda _b: Gtk.FileLauncher.new(
            Gio.File.new_for_path(chronicle.quotes_path(session))).launch(self.get_root(), None, None))
        label = Gtk.Label(label="Cytaty sesji", xalign=0, hexpand=True, css_classes=["dim-label"])
        bar = Gtk.Box(spacing=6, margin_top=10, margin_start=24, margin_end=12)
        for widget in (label, edit, again):
            bar.append(widget)

        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=24,
                        margin_start=32, margin_end=32)
        for text, who in quotes:
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            quote = Gtk.Label(label=f"„{text}”", xalign=0, wrap=True, selectable=True)
            quote.add_css_class("title-4")
            item.append(quote)
            if who:
                item.append(Gtk.Label(label=f"— {who}", xalign=1, css_classes=["dim-label"]))
            items.append(item)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(Gtk.ScrolledWindow(child=items, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        return box

    def _ask_revision(self, session: Session) -> None:
        """Okno z poleceniem poprawki; AI zmienia tylko to, czego dotyczy polecenie."""
        buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                            left_margin=10, right_margin=10, accepts_tab=False)
        view.add_css_class("card")
        scrolled = Gtk.ScrolledWindow(child=view, min_content_height=110, hscrollbar_policy=Gtk.PolicyType.NEVER)
        dialog = Adw.AlertDialog(
            heading="Popraw kronikę",
            body="Napisz, co zmienić - AI poprawi tylko to, resztę zostawi bez zmian. Na przykład: „to nie Hans, "
                 "tylko Hanna”, „dodaj walkę z trollem przy moście”, „Eustachos nie był ranny”. "
                 "Poprzednią wersję można przywrócić przyciskiem „Cofnij poprawkę”.",
            extra_child=scrolled)
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("revise", "Popraw")
        dialog.set_response_appearance("revise", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("revise", False)
        buffer.connect("changed", lambda b: dialog.set_response_enabled("revise", bool(_text(b).strip())))

        def on_response(_d, response):
            if response == "revise" and _text(buffer).strip():
                self._revise(session, _text(buffer).strip())

        dialog.connect("response", on_response)
        dialog.present(self.get_root())
        view.grab_focus()

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


def _text(buffer: Gtk.TextBuffer) -> str:
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
