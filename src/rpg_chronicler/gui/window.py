"""Główne okno: lista sesji, szczegóły (transkrypcja / mówcy / kronika) i pasek zadań.

Zakładki i pasek zadań są w osobnych modułach (transcript_page, speakers_page, chronicle_page, task_bar);
okno składa je w całość, trzyma listę sesji i uruchamia zadania (TaskRunner).
"""
import os
import sys

from gi.repository import Adw, Gio, GLib, Gtk

from .. import backfill, chronicle, deletion, glossary, memory, settings
from ..campaigns import campaign_key
from ..config import LLM_PROVIDER
from ..session import Session, list_sessions
from .campaigns_view import CampaignsView
from .chronicle_page import ChroniclePage
from .discord_dialog import DiscordDialog
from .notes_dialog import NotesDialog
from .environment import EnvironmentBanner
from .player import SnippetPlayer
from .search_dialog import SearchDialog
from .settings_dialog import PROVIDERS, SettingsDialog
from .speakers_page import SpeakersPage
from .task_bar import TaskBar
from .tasks import TaskRunner
from .text import (ALL_CAMPAIGNS, campaign_filter_options, new_proposals, proposals_snapshot, session_campaign,
                   session_signature, session_stage)
from .transcript_page import TranscriptPage
from .widgets import icon_button

TASK_ACTIONS = ("sync", "upload", "run", "run-offline")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="RPG Chronicler", default_width=1180, default_height=760,
                         maximized=True)   # rozmiar domyślny - po wyjściu z maksymalizacji
        self.sessions: list[Session] = []
        self.current: Session | None = None
        self._list_signature = None
        self._detail_signature = None
        self._rows: dict[str, Adw.ActionRow] = {}
        self._row_campaigns: dict[str, str] = {}
        self._session_task_buttons: list[Gtk.Button] = []
        self._discord_dialog: DiscordDialog | None = None
        self._open_pdf_after: str | None = None
        self._proposals_before: dict = {}
        self.campaign_filter: str | None = ALL_CAMPAIGNS
        self._filter_keys: list[str | None] = []
        self._updating_filter = False

        self.runner = TaskRunner()
        self.runner.connect("line", self._on_task_line)
        self.runner.connect("status", lambda _r, text: self.task_bar.set_detail(text))
        self.runner.connect("progress", lambda _r, stage, session, fraction:
                            self.task_bar.show_progress(stage, session, fraction))
        self.runner.connect("finished", self._on_task_finished)

        self.player = SnippetPlayer()
        self.player.connect("error", lambda _p, msg: self.toast(f"Nie można odtworzyć nagrania: {msg}"))

        self.log_buffer = Gtk.TextBuffer()
        self._setup_actions()
        self._build_ui()
        self.refresh()
        self.env_banner.check()
        self.connect("notify::is-active", lambda w, _p: w.is_active() and self.refresh())
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------ akcje

    def _setup_actions(self) -> None:
        def add(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: callback())
            self.add_action(action)

        add("refresh", lambda: self.refresh(force=True))
        add("sync", lambda: self.start_task("Pobieranie z Google Drive", ["sync"]))
        add("upload", lambda: self.start_task("Wysyłanie na Google Drive", ["upload"]))
        add("run", lambda: self.start_task("Pełny przebieg", ["run", "--no-interactive", *self._provider_args()]))
        add("run-offline", lambda: self.start_task(
            "Przebieg bez Google Drive", ["run", "--offline", "--no-interactive", *self._provider_args()]))
        add("show-log", self.show_log)
        add("preferences", self.show_settings)
        add("campaigns", lambda: self.show_campaigns(None))
        add("sessions", self.show_sessions)
        add("search", self.show_search)
        add("add-notes", lambda: self.show_notes_dialog(None))
        for scope in deletion.SCOPES:
            add(f"delete-{scope}", lambda s=scope: self.confirm_delete(s))
        add("backfill", self.show_backfill)
        add("restart", self.restart)
        add("cancel", self.runner.cancel)

        self.provider_action = Gio.SimpleAction.new_stateful(
            "provider", GLib.VariantType.new("s"), GLib.Variant.new_string(LLM_PROVIDER))
        self.provider_action.connect("activate", self._on_provider_activated)
        self.add_action(self.provider_action)

    def _on_provider_activated(self, action, value) -> None:
        action.set_state(value)
        try:
            settings.update({"ai.dostawca": value.get_string()})
        except OSError as e:
            self.toast(f"Nie można zapisać ustawień: {e}")

    @property
    def provider(self) -> str:
        return self.provider_action.get_state().get_string()

    def _provider_args(self) -> list[str]:
        return ["--provider", self.provider]

    def _provider_label(self) -> str:
        return dict(PROVIDERS).get(self.provider, self.provider)

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self) -> None:
        self.main_menu = self._build_main_menu()
        self.main_stack = Adw.ViewStack()
        self.split = Adw.NavigationSplitView(min_sidebar_width=280, max_sidebar_width=360)
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self._build_content())
        self.campaigns_view = CampaignsView(self.start_task, lambda: self.provider, self._register_task_button,
                                            self.toast, self._sidebar_header, self._open_session_from_campaign)
        self.main_stack.add_titled_with_icon(self.split, "sesje", "Sesje", "audio-x-generic-symbolic")
        self.main_stack.add_titled_with_icon(self.campaigns_view, "kampanie", "Kampanie", "system-users-symbolic")
        self.main_stack.connect("notify::visible-child-name", self._on_main_tab_changed)

        outer = Adw.ToolbarView(content=self.main_stack)
        self.env_banner = EnvironmentBanner()
        outer.add_top_bar(self.env_banner)
        self.task_bar = TaskBar()
        outer.add_bottom_bar(self.task_bar)

        self.toasts = Adw.ToastOverlay(child=outer)
        self.set_content(self.toasts)

        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        breakpoint_.add_setter(self.split, "collapsed", True)
        breakpoint_.add_setter(self.campaigns_view.split, "collapsed", True)
        self.add_breakpoint(breakpoint_)

    def _build_main_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Odśwież listę", "win.refresh")
        section.append("Pobierz z Google Drive", "win.sync")
        section.append("Wyślij na Google Drive", "win.upload")
        menu.append_section(None, section)
        providers = Gio.Menu()
        for key, label in PROVIDERS:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value("win.provider", GLib.Variant.new_string(key))
            providers.append_item(item)
        menu.append_section("Dostawca AI", providers)
        other = Gio.Menu()
        other.append("Szukaj w sesjach", "win.search")
        other.append("Dodaj sesję z notatek…", "win.add-notes")
        other.append("Uzupełnij brakujące…", "win.backfill")
        other.append("Ustawienia", "win.preferences")
        other.append("Pokaż log", "win.show-log")
        menu.append_section(None, other)
        return menu

    def _sidebar_header(self) -> Adw.HeaderBar:
        """Nagłówek nad listą (sesji albo kampanii): przełącznik Sesje/Kampanie i menu główne."""
        header = Adw.HeaderBar(title_widget=Adw.InlineViewSwitcher(stack=self.main_stack,
                                                                   tooltip_text="Sesje (Ctrl+1) / Kampanie (Ctrl+K)"))
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self.main_menu,
                                       tooltip_text="Menu główne", primary=True))
        return header

    def _build_sidebar(self) -> Adw.NavigationPage:
        header = self._sidebar_header()
        self.session_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.session_list.add_css_class("navigation-sidebar")
        self.session_list.connect("row-selected", self._on_row_selected)
        self.session_list.set_filter_func(self._row_visible)
        self.session_list.set_placeholder(Gtk.Label(
            label="Brak sesji.\nPobierz nagrania z Google Drive.", justify=Gtk.Justification.CENTER,
            margin_top=24, css_classes=["dim-label"]))
        scrolled = Gtk.ScrolledWindow(child=self.session_list, vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)

        run_menu = Gio.Menu()
        run_menu.append("Bez Google Drive (tylko lokalnie)", "win.run-offline")
        run_button = Adw.SplitButton(label="Przetwórz wszystko", menu_model=run_menu, action_name="win.run",
                                     tooltip_text="Pobierz, transkrybuj, wygeneruj kroniki i wyślij na Drive",
                                     margin_top=6, margin_bottom=12, margin_start=12, margin_end=12)
        run_button.add_css_class("suggested-action")

        self.filter_dropdown = Gtk.DropDown(model=Gtk.StringList(), tooltip_text="Pokaż sesje jednej kampanii",
                                            hexpand=True, visible=False)
        self.filter_dropdown.connect("notify::selected", self._on_filter_changed)
        tools = Gtk.Box(spacing=2, margin_start=12, margin_end=6, margin_bottom=6)
        tools.append(self.filter_dropdown)
        tools.append(Gtk.Box(hexpand=True))   # przyciski zostają po prawej, gdy filtra nie ma
        for icon, tooltip, action in (
                ("system-search-symbolic", "Szukaj w kronikach i transkrypcjach (Ctrl+F)", "win.search"),
                ("list-add-symbolic", "Dodaj sesję bez nagrania - kronika z notatek MG (Ctrl+N)", "win.add-notes")):
            button = icon_button(icon, tooltip, action)
            button.add_css_class("flat")
            tools.append(button)

        view = Adw.ToolbarView(content=scrolled)
        view.add_top_bar(header)
        view.add_top_bar(tools)
        view.add_bottom_bar(run_button)
        return Adw.NavigationPage(title="Sesje", child=view)

    def _build_content(self) -> Adw.NavigationPage:
        self.view_stack = Adw.ViewStack()
        self.transcript_page = TranscriptPage(self.player, self.start_task, self._register_task_button,
                                              lambda s: self.show_notes_dialog(s))
        self.speakers_page = SpeakersPage(self.player, self.suggest_speakers, self._on_speakers_saved, self.start_task)
        self.chronicle_page = ChroniclePage(
            summarize=self.summarize, write_brief=self.write_brief, revise=self.revise,
            undo_revision=self.undo_revision, write_quotes=self.write_quotes, open_pdf=self.open_pdf,
            show_discord=self.show_discord, provider_label=self._provider_label,
            register_task_button=self._register_task_button, player=self.player)
        self.view_stack.add_titled_with_icon(self.transcript_page, "transcript", "Transkrypcja",
                                             "text-x-generic-symbolic")
        self.view_stack.add_titled_with_icon(self.speakers_page, "speakers", "Mówcy", "system-users-symbolic")
        self.view_stack.add_titled_with_icon(self.chronicle_page, "summary", "Kronika", "x-office-document-symbolic")

        self.content_header = Adw.HeaderBar(
            title_widget=Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.campaign_button = Gtk.Button(tooltip_text="Opis świata, postacie graczy i słownik nazw tej kampanii")
        self.campaign_button.connect("clicked", lambda _b: self.current and self.show_campaigns(
            self.current.campaign.key or None))
        session_menu = Gio.Menu()
        session_menu.append("Usuń kronikę…", f"win.delete-{deletion.CHRONICLE}")
        session_menu.append("Zacznij od nowa (zostaw nagranie)…", f"win.delete-{deletion.RESTART}")
        session_menu.append("Usuń całą sesję…", f"win.delete-{deletion.SESSION}")
        self.content_header.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=session_menu,
                                                    tooltip_text="Usuwanie kroniki albo sesji"))
        self.content_header.pack_end(self.campaign_button)
        session_view = Adw.ToolbarView(content=self.view_stack)
        session_view.add_top_bar(self.content_header)

        empty_view = Adw.ToolbarView(content=Adw.StatusPage(
            icon_name="audio-x-generic-symbolic", title="Wybierz sesję",
            description="Po lewej są wszystkie nagrania i transkrypcje. "
                        "Wybierz jedną, żeby przejrzeć transkrypcję, nazwać mówców albo przeczytać kronikę."))
        empty_view.add_top_bar(Adw.HeaderBar(show_title=False))

        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.add_named(empty_view, "empty")
        self.content_stack.add_named(session_view, "session")
        self.content_page = Adw.NavigationPage(title="RPG Chronicler", child=self.content_stack)
        return self.content_page

    # ------------------------------------------------------------ lista sesji

    def refresh(self, force: bool = False) -> None:
        """Odczytuje stan sesji z dysku i przebudowuje tylko to, co się zmieniło."""
        try:
            self.sessions = list_sessions()
        except OSError as e:
            self.toast(f"Nie można odczytać sesji: {e}")
            return
        signature = [(s.name, session_signature(s)) for s in self.sessions]
        if force or signature != self._list_signature:
            self._list_signature = signature
            self._rebuild_list()
        if self.current is not None:
            current = next((s for s in self.sessions if s.name == self.current.name), None)
            if current is None:
                self._show_session(None)
            elif force or session_signature(current) != self._detail_signature:
                self._show_session(current, keep_view=True)

    def _rebuild_list(self) -> None:
        selected = self.current.name if self.current else None
        self._rows = {}
        self._row_campaigns = {s.name: session_campaign(s) for s in self.sessions}
        self.session_list.remove_all()
        for session in self.sessions:
            stage, done = session_stage(session)
            row = Adw.ActionRow(title=session.name, subtitle=f"{session.system_name} · {stage}", use_markup=False)
            if done:
                icon = Gtk.Image(icon_name="object-select-symbolic", tooltip_text="Transkrypcja, mówcy i kronika gotowe")
                icon.add_css_class("success")
            else:
                icon = Gtk.Image(icon_name="content-loading-symbolic", tooltip_text=stage)
                icon.add_css_class("dim-label")
            row.add_suffix(icon)
            self._rows[session.name] = row
            self.session_list.append(row)
        self._update_filter_options()
        if selected in self._rows:
            self.session_list.select_row(self._rows[selected])

    def _update_filter_options(self) -> None:
        """Kampanie w filtrze (z liczbą sesji); wybór zostaje, dopóki kampania ma sesje."""
        options = campaign_filter_options(self.sessions)
        keys = [key for key, _label in options]
        if self.campaign_filter not in keys:
            self.campaign_filter = ALL_CAMPAIGNS
        self._updating_filter = True
        self._filter_keys = keys
        self.filter_dropdown.set_model(Gtk.StringList.new([label for _key, label in options]))
        self.filter_dropdown.set_selected(keys.index(self.campaign_filter))
        self._updating_filter = False
        self.filter_dropdown.set_visible(len(keys) > 2)   # filtr ma sens przy co najmniej dwóch kampaniach
        self.session_list.invalidate_filter()

    def _on_filter_changed(self, dropdown, _param) -> None:
        index = dropdown.get_selected()
        if self._updating_filter or index >= len(self._filter_keys):
            return
        self.set_campaign_filter(self._filter_keys[index])

    def set_campaign_filter(self, key: str | None) -> None:
        self.campaign_filter = key
        if key in self._filter_keys and self.filter_dropdown.get_selected() != self._filter_keys.index(key):
            self.filter_dropdown.set_selected(self._filter_keys.index(key))  # wywoła _on_filter_changed
            return
        self.session_list.invalidate_filter()

    def _row_visible(self, row) -> bool:
        if self.campaign_filter is ALL_CAMPAIGNS:
            return True
        return self._row_campaigns.get(row.get_title()) == self.campaign_filter

    def _on_row_selected(self, _list, row) -> None:
        if row is None:
            return
        session = next((s for s in self.sessions if s.name == row.get_title()), None)
        if session is None or self.current is not None and session.name == self.current.name:
            return
        self._autosave_speakers()
        self._show_session(session)
        self.split.set_show_content(True)

    # ------------------------------------------------------- szczegóły sesji

    def _show_session(self, session: Session | None, keep_view: bool = False) -> None:
        self.player.stop()
        self.current = session
        if session is None:
            self.content_stack.set_visible_child_name("empty")
            self.content_page.set_title("RPG Chronicler")
            return

        self._detail_signature = session_signature(session)
        self.content_page.set_title(session.name)
        key = session.campaign.key
        self.campaign_button.set_visible(bool(key))
        pending = glossary.count_proposals(glossary.pending_for(session.campaign)) if key else 0
        pending += 1 if key and memory.load_proposal(key) is not None else 0
        self.campaign_button.set_label(f"Kampania {key}" + (f" ({pending})" if pending else ""))
        self.content_stack.set_visible_child_name("session")

        transcript = None
        if session.has_transcript:
            try:
                transcript = session.load_transcript()
            except (OSError, ValueError) as e:
                self.toast(f"Nie można wczytać transkrypcji: {e}")

        keep_edits = None
        if keep_view and self.speakers_page.session and self.speakers_page.session.name == session.name \
                and self.speakers_page.dirty:
            keep_edits = self.speakers_page.edits()

        busy = self.runner.running
        self.transcript_page.set_busy(busy)
        self.transcript_page.show_session(session, transcript)
        self.speakers_page.show_session(session, transcript, keep_edits)
        self.speakers_page.set_busy(busy)
        self.chronicle_page.show_session(session)
        self._update_delete_actions()
        from_notes = session.has_notes and not session.has_transcript
        self.view_stack.get_page(self.transcript_page).set_title("Notatki" if from_notes else "Transkrypcja")
        self.view_stack.get_page(self.speakers_page).set_visible(not from_notes)

        if not keep_view:
            stage, _ = session_stage(session)
            page = {"czeka na transkrypcję": "transcript", "mówcy bez imion": "speakers"}.get(stage, "summary")
            if page == "summary" and not session.has_summary and not session.has_source:
                page = "transcript"
            self.view_stack.set_visible_child_name(page)

    def _register_task_button(self, button: Gtk.Button) -> None:
        """Przycisk uruchamiający zadanie - nieaktywny, gdy inne zadanie jest w toku."""
        button.set_sensitive(not self.runner.running)
        self._session_task_buttons.append(button)

    # ------------------------------------------------------------ operacje

    def summarize(self, session: Session, force: bool = False) -> None:
        def start(allow_unnamed: bool):
            args = ["summarize", "--no-interactive", *self._provider_args()]
            if allow_unnamed:
                args.append("--allow-unnamed")
            if force:
                args.append("--force")
            self.start_task(f"Kronika {session.name}", args + [session.name])

        def run(allow_unnamed: bool):
            """Najpierw ostrzeżenie o niezatwierdzonym stanie kampanii (kronika by go nie znała)."""
            key = campaign_key(session.name)
            warning = memory.unaccepted_warning(key, session.name)
            if warning is None:
                start(allow_unnamed)
                return
            dialog = Adw.AlertDialog(
                heading="Stan kampanii czeka na zatwierdzenie",
                body=f"{warning}\n\nZatwierdź propozycję w oknie „Kampanie”, żeby kronika znała najnowszy stan świata.")
            dialog.add_response("cancel", "Anuluj")
            dialog.add_response("campaigns", "Otwórz Kampanie")
            dialog.add_response("generate", "Generuj mimo to")
            dialog.set_response_appearance("campaigns", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("campaigns")
            dialog.connect("response", lambda _d, r: self.show_campaigns(key) if r == "campaigns"
                           else r == "generate" and start(allow_unnamed))
            dialog.present(self)

        self._autosave_speakers()
        if session.has_transcript and not session.has_speakers and session.load_transcript().speakers:
            dialog = Adw.AlertDialog(
                heading="Mówcy nie mają imion",
                body="Kronika powstanie z etykietami SPEAKER_00, SPEAKER_01… zamiast imion postaci. "
                     "Lepiej najpierw nazwać mówców w zakładce „Mówcy”.")
            dialog.add_response("cancel", "Anuluj")
            dialog.add_response("speakers", "Nazwij mówców")
            dialog.add_response("generate", "Generuj mimo to")
            dialog.set_response_appearance("speakers", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("speakers")

            def on_response(_d, response):
                if response == "speakers":
                    self.view_stack.set_visible_child_name("speakers")
                elif response == "generate":
                    run(True)

            dialog.connect("response", on_response)
            dialog.present(self)
        elif force:
            dialog = Adw.AlertDialog(heading="Wygenerować kronikę ponownie?",
                                     body="Obecna kronika zostanie zastąpiona nową wersją.")
            dialog.add_response("cancel", "Anuluj")
            dialog.add_response("generate", "Generuj ponownie")
            dialog.set_response_appearance("generate", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect("response", lambda _d, r: r == "generate" and run(False))
            dialog.present(self)
        else:
            run(False)

    def write_brief(self, session: Session, force: bool = False) -> None:
        args = ["brief", session.name, *self._provider_args()] + (["--force"] if force else [])
        self.start_task(f"Skrót kroniki {session.name}", args)

    def write_quotes(self, session: Session, force: bool = False) -> None:
        args = ["quotes", session.name, *self._provider_args()] + (["--force"] if force else [])
        self.start_task(f"Cytaty z sesji {session.name}", args)

    def revise(self, session: Session, instruction: str) -> None:
        self.start_task(f"Poprawka kroniki {session.name}",
                        ["revise", session.name, instruction, *self._provider_args()])

    def undo_revision(self, session: Session) -> None:
        dialog = Adw.AlertDialog(heading="Cofnąć ostatnią poprawkę?",
                                 body="Kronika wróci do wersji sprzed ostatniej poprawki. Skrót kroniki "
                                      "trzeba będzie napisać ponownie (zakładka Kronika → Skrót).")
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("undo", "Cofnij poprawkę")
        dialog.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, r: r == "undo" and self.start_task(
            f"Cofnięcie poprawki {session.name}", ["revise", session.name, "--undo"]))
        dialog.present(self)

    def suggest_speakers(self, session: Session) -> None:
        self.start_task(f"Sugestia mówców {session.name}",
                        ["speakers", "--suggest-only", *self._provider_args(), session.name])

    def _on_speakers_saved(self, session: Session) -> None:
        self.refresh()
        if not session.has_summary:
            toast = Adw.Toast(title="Zapisano mówców", button_label="Generuj kronikę")
            toast.connect("button-clicked", lambda _t: self.summarize(session))
            self.toasts.add_toast(toast)
        else:
            self.toast("Zapisano mówców")

    def _autosave_speakers(self) -> None:
        """Zapisuje niezapisane imiona mówców (przy zmianie sesji, generowaniu kroniki, zamykaniu)."""
        if self.speakers_page.dirty and self.speakers_page.save(notify=False):
            self.toast(f"Zapisano mówców sesji {self.speakers_page.session.name}")
            GLib.idle_add(lambda: self.refresh() or GLib.SOURCE_REMOVE)

    def open_pdf(self, session: Session) -> None:
        """Otwiera aktualny PDF kroniki; jeśli go nie ma albo jest starszy niż kronika - najpierw go tworzy."""
        if chronicle.pdf_is_current(session):
            Gtk.FileLauncher.new(Gio.File.new_for_path(chronicle.pdf_path(session))).launch(self, None, None)
            return
        self._open_pdf_after = session.name
        self.start_task(f"PDF {session.name}", ["pdf", session.name])

    # ------------------------------------------------------------ zadania

    def start_task(self, title: str, args: list[str]) -> None:
        error = self.runner.start(title, args)
        if error:
            self.toast(error)
            return
        self._proposals_before = proposals_snapshot()
        self.task_bar.start(title)
        self._set_busy(True)

    def _set_busy(self, busy: bool) -> None:
        for name in TASK_ACTIONS:
            self.lookup_action(name).set_enabled(not busy)
        self.lookup_action("cancel").set_enabled(busy)
        self._session_task_buttons = [b for b in self._session_task_buttons if b.get_root() is not None]
        for button in self._session_task_buttons:
            button.set_sensitive(not busy)
        self._update_delete_actions()
        self.speakers_page.set_busy(busy)
        self.transcript_page.set_busy(busy)

    def _on_task_line(self, _runner, line: str) -> None:
        self.log_buffer.insert(self.log_buffer.get_end_iter(), line + "\n")
        self.task_bar.show_line(line)

    def _on_task_finished(self, _runner, title: str, success: bool, description: str) -> None:
        self.player.close_file()
        elapsed = self.task_bar.finish()
        self._set_busy(False)
        if success:
            self.toast(f"{title}: gotowe ({elapsed})")
        else:
            toast = Adw.Toast(title=f"{title}: {description}", button_label="Pokaż log", timeout=0)
            toast.connect("button-clicked", lambda _t: self.show_log())
            self.toasts.add_toast(toast)
        self.refresh(force=True)
        self.campaigns_view.reload()
        if self._discord_dialog is not None:
            self._discord_dialog.reload()
        self._notify_new_proposals()
        pdf_session, self._open_pdf_after = self._open_pdf_after, None
        if success and pdf_session:
            session = next((s for s in self.sessions if s.name == pdf_session), None)
            if session is not None and chronicle.pdf_is_current(session):
                Gtk.FileLauncher.new(Gio.File.new_for_path(chronicle.pdf_path(session))).launch(self, None, None)

    def _notify_new_proposals(self) -> None:
        """Toast, gdy zadanie (kronika, „Uzupełnij z kronik”) dodało propozycje do słownika lub stanu kampanii."""
        for key, message in new_proposals(self._proposals_before, proposals_snapshot()):
            toast = Adw.Toast(title=GLib.markup_escape_text(message), button_label="Przejrzyj", timeout=0)
            toast.connect("button-clicked", lambda _t, k=key: self.show_campaigns(k))
            self.toasts.add_toast(toast)

    def show_log(self) -> None:
        view = Gtk.TextView(buffer=self.log_buffer, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12, bottom_margin=12,
                            left_margin=12, right_margin=12)
        scrolled = Gtk.ScrolledWindow(child=view, vexpand=True)
        GLib.idle_add(lambda: view.scroll_to_mark(self.log_buffer.get_insert(), 0, False, 0, 1) and False)
        self.log_buffer.place_cursor(self.log_buffer.get_end_iter())
        body = Adw.ToolbarView(content=scrolled)
        body.add_top_bar(Adw.HeaderBar())
        Adw.Dialog(title="Log zadań", child=body, content_width=900, content_height=600).present(self)

    # ------------------------------------------------------------ okna dialogowe

    def show_discord(self, session: Session) -> None:
        if self._discord_dialog is not None:
            self._discord_dialog.force_close()
        dialog = DiscordDialog(session, self.start_task, lambda: self.provider, self._register_task_button,
                               self.show_campaigns)

        def closed(_d):
            if self._discord_dialog is dialog:
                self._discord_dialog = None

        dialog.connect("closed", closed)
        self._discord_dialog = dialog
        dialog.present(self)

    def show_campaigns(self, key: str | None) -> None:
        """Zakładka „Kampanie”, z otwartą kampanią `key` (None - ostatnio otwarta albo kampania bieżącej sesji)."""
        self.main_stack.set_visible_child_name("kampanie")
        if key is None and self.campaigns_view.current_key is None and self.current is not None:
            key = self.current.campaign.key or None
        if key is not None:
            self.campaigns_view.open_campaign(key)

    def show_sessions(self) -> None:
        self.main_stack.set_visible_child_name("sesje")

    def _open_session_from_campaign(self, name: str) -> None:
        self.show_sessions()
        self.open_session(name, "summary")

    def _on_main_tab_changed(self, stack, _param) -> None:
        if stack.get_visible_child_name() == "sesje":
            self.refresh(force=True)   # zmiany w kampanii (system, imiona) widać w liście i transkrypcji
        else:
            self.campaigns_view.reload()

    def show_backfill(self) -> None:
        """„Uzupełnij brakujące”: plan (skróty, cytaty, PDF-y, encyklopedie, dzienniki) i potwierdzenie."""
        steps = backfill.plan(list_sessions())
        if not steps:
            self.toast("Wszystko jest aktualne - nie ma czego uzupełniać")
            return
        requests = backfill.ai_requests(steps)
        dialog = Adw.AlertDialog(
            heading="Uzupełnić brakujące?",
            body=f"{backfill.summary(steps)}\n\nZapytań do AI: ok. {requests} ({self._provider_label()}). "
                 "Gotowe pliki zostają, powstają tylko brakujące i nieaktualne.")
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("run", "Uzupełnij")
        dialog.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("run")
        dialog.connect("response", lambda _d, r: r == "run" and self.start_task(
            "Uzupełnianie brakujących", ["backfill", *self._provider_args()]))
        dialog.present(self)

    def _update_delete_actions(self) -> None:
        """Usuwanie: kronika - gdy jest; „od nowa” - gdy jest nagranie i coś poza nim; nic w trakcie zadania."""
        session, idle = self.current, not self.runner.running
        enabled = {deletion.CHRONICLE: session is not None and session.has_summary,
                   deletion.RESTART: session is not None and session.audio_path is not None
                   and (session.has_source or session.has_summary),
                   deletion.SESSION: session is not None}
        for scope, ok in enabled.items():
            self.lookup_action(f"delete-{scope}").set_enabled(idle and ok)

    def confirm_delete(self, scope: str) -> None:
        """Okno z listą plików; cała sesja wymaga zaznaczenia „Rozumiem…”. Usuwa zadanie `delete` (z Drive)."""
        session = self.current
        if session is None:
            return
        try:
            plan = deletion.plan(session.name, scope)
        except deletion.DeletionError as e:
            self.toast(str(e))
            return
        headings = {deletion.CHRONICLE: "Usunąć kronikę?", deletion.RESTART: "Zacząć sesję od nowa?",
                    deletion.SESSION: "Usunąć całą sesję?"}
        effects = {
            deletion.CHRONICLE: "Kronika, skrót, cytaty, PDF i zapowiedź znikną. Transkrypcja"
                                + (" i notatki zostają" if session.has_notes else " i mówcy zostają")
                                + " - kronikę można potem napisać od nowa.",
            deletion.RESTART: "Zostanie tylko nagranie. Znikną transkrypcja, mówcy, odciski głosu, kronika i wszystko, "
                              "co z niej powstało - sesja wróci do etapu „czeka na transkrypcję”.",
            deletion.SESSION: "Sesja zniknie z listy: nagranie, transkrypcja albo notatki, kronika i wszystko, "
                              "co z nich powstało.",
        }
        body = (f"{effects[scope]}\n\nPliki ({len(plan.files)}) zostaną usunięte z dysku i z Google Drive. "
                f"Przez {deletion.TRASH_DAYS} dni będą w koszu Google Drive i w koszu aplikacji "
                f"(przywrócenie: rpg-chronicler delete {session.name} --undo).")
        files = Gtk.Label(label=deletion.describe(plan), wrap=True, xalign=0, selectable=True,
                          css_classes=["dim-label", "caption"])
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        extra.append(Gtk.ScrolledWindow(child=files, max_content_height=160, propagate_natural_height=True,
                                        hscrollbar_policy=Gtk.PolicyType.NEVER))
        dialog = Adw.AlertDialog(heading=headings[scope], body=body, extra_child=extra)
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("delete", "Usuń" if scope != deletion.RESTART else "Usuń i zacznij od nowa")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        if scope == deletion.SESSION:   # pełne wymazanie: świadome potwierdzenie
            understand = Gtk.CheckButton(label="Rozumiem, że usuwam całą sesję razem z nagraniem")
            understand.connect("toggled", lambda b: dialog.set_response_enabled("delete", b.get_active()))
            extra.append(understand)
            dialog.set_response_enabled("delete", False)
        dialog.connect("response", lambda _d, r: r == "delete" and self.start_task(
            f"Usuwanie: {deletion.SCOPE_LABELS[scope]} ({session.name})",
            ["delete", session.name, "--zakres", scope, "--yes"]))
        dialog.present(self)

    def show_notes_dialog(self, session: Session | None) -> None:
        """Nowa sesja z notatek (`session` None) albo edycja notatek istniejącej."""
        def saved(name: str, generate: bool) -> None:
            self.refresh(force=True)
            self.open_session(name, "summary" if generate else "transcript")
            target = next((s for s in self.sessions if s.name == name), None)
            if generate and target is not None:
                self.summarize(target, force=target.has_summary)
            else:
                self.toast(f"Zapisano notatki sesji {name}")

        campaign = self.campaign_filter or (self.current.campaign.key if self.current is not None else None)
        NotesDialog(saved, campaign or None, session).present(self)

    def show_search(self) -> None:
        campaign = self.current.campaign.key if self.current is not None else None
        SearchDialog(lambda: self.sessions, self.player, self.open_session, campaign or None).present(self)

    def open_session(self, name: str, page: str) -> None:
        """Pokazuje sesję na wskazanej zakładce (np. z wyniku wyszukiwania)."""
        row = self._rows.get(name)
        if row is None:
            self.toast(f"Nie ma już sesji {name}")
            return
        if not self._row_visible(row):   # np. wynik wyszukiwania z innej kampanii niż filtr
            self.set_campaign_filter(ALL_CAMPAIGNS)
        self.main_stack.set_visible_child_name("sesje")
        self.session_list.select_row(row)  # wywoła _on_row_selected → _show_session
        self.view_stack.set_visible_child_name(page)
        self.split.set_show_content(True)

    def show_settings(self) -> None:
        def provider_changed(key: str) -> None:
            self.provider_action.set_state(GLib.Variant.new_string(key))

        def folders_changed() -> None:
            toast = Adw.Toast(title="Zmieniono foldery – zadziałają po ponownym uruchomieniu",
                              button_label="Uruchom ponownie", action_name="win.restart", timeout=0)
            self.toasts.add_toast(toast)

        SettingsDialog(self.provider, provider_changed, folders_changed).present(self)

    # ------------------------------------------------------------ okno

    def restart(self) -> None:
        """Uruchamia GUI od nowa w tym samym procesie (np. po zmianie folderów)."""
        if self.runner.running:
            self.toast("Poczekaj na koniec zadania albo je przerwij")
            return
        self._autosave_speakers()
        self.player.stop()
        os.execv(sys.executable, [sys.executable, "-m", "rpg_chronicler.gui"])

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))

    def _on_close_request(self, _window) -> bool:
        self._autosave_speakers()
        self.player.stop()
        if not self.runner.running:
            return False
        dialog = Adw.AlertDialog(heading="Zadanie jest w toku",
                                 body=f"„{self.runner.title}” zostanie przerwane. Zamknąć mimo to?")
        dialog.add_response("cancel", "Nie zamykaj")
        dialog.add_response("close", "Przerwij i zamknij")
        dialog.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, response):
            if response == "close":
                self.runner.connect("finished", lambda *_: self.destroy())
                self.runner.cancel()

        dialog.connect("response", on_response)
        dialog.present(self)
        return True
