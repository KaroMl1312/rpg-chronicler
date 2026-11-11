"""Główne okno: lista sesji, szczegóły (transkrypcja / mówcy / kronika) i pasek zadań."""
import os
import sys
import time

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import chronicle, glossary, settings
from ..config import LLM_PROVIDER, PROJECT_ROOT
from ..session import Session, list_sessions
from ..transcript import Transcript, load_speaker_mapping
from .campaigns_dialog import CampaignsDialog
from .discord_dialog import DiscordDialog
from .player import SnippetPlayer
from .recording_page import RecordingPanel
from .settings_dialog import PROVIDERS, SettingsDialog
from .speakers_page import SpeakersPage
from .tasks import TaskRunner
from .text import (estimate_remaining, format_minutes, format_timestamp, markdown_spans,
                   session_signature, session_stage, transcript_blocks)

SPEAKER_COLORS = ["#3584e4", "#e66100", "#26a269", "#9141ac", "#c64600", "#1c71d8", "#a51d2d", "#865e3c"]
TASK_ACTIONS = ("sync", "upload", "run", "run-offline")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="RPG Chronicler", default_width=1180, default_height=760)
        self.sessions: list[Session] = []
        self.current: Session | None = None
        self._list_signature = None
        self._detail_signature = None
        self._rows: dict[str, Adw.ActionRow] = {}
        self._task_started = 0.0
        self._stage_key = None
        self._stage_started = 0.0
        self._pulse_id = 0
        self._session_task_buttons: list[Gtk.Button] = []
        self.recording_panel: RecordingPanel | None = None
        self._campaigns_dialog: CampaignsDialog | None = None
        self._discord_dialog: DiscordDialog | None = None
        self._open_pdf_after: str | None = None
        self._chronicle_mode = "kronika"  # przełącznik „Kronika / Skrót” w zakładce Kronika
        self._proposal_counts: dict[str, int] = {}

        self.runner = TaskRunner()
        self.runner.connect("line", self._on_task_line)
        self.runner.connect("status", lambda _r, text: self.task_detail.set_text(text))
        self.runner.connect("progress", self._on_task_progress)
        self.runner.connect("finished", self._on_task_finished)

        self.player = SnippetPlayer()
        self.player.connect("error", lambda _p, msg: self.toast(f"Nie można odtworzyć nagrania: {msg}"))

        self.log_buffer = Gtk.TextBuffer()
        self._setup_actions()
        self._build_ui()
        self.refresh()
        self._check_environment()
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

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self) -> None:
        self.split = Adw.NavigationSplitView(min_sidebar_width=280, max_sidebar_width=360)
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self._build_content())

        outer = Adw.ToolbarView(content=self.split)
        self.env_banner = Adw.Banner(button_label="Jak naprawić")
        self.env_banner.connect("button-clicked", lambda _b: self._show_environment_help())
        self._environment_error = ""
        outer.add_top_bar(self.env_banner)
        outer.add_bottom_bar(self._build_task_bar())

        self.toasts = Adw.ToastOverlay(child=outer)
        self.set_content(self.toasts)

        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        breakpoint_.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint_)

    def _build_sidebar(self) -> Adw.NavigationPage:
        header = Adw.HeaderBar()
        header.pack_start(_icon_button("view-refresh-symbolic", "Odśwież listę (Ctrl+R)", "win.refresh"))

        menu = Gio.Menu()
        section = Gio.Menu()
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
        other.append("Kampanie", "win.campaigns")
        other.append("Ustawienia", "win.preferences")
        other.append("Pokaż log", "win.show-log")
        menu.append_section(None, other)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Menu główne", primary=True))
        header.pack_end(_icon_button("folder-download-symbolic", "Pobierz nowe nagrania z Google Drive", "win.sync"))

        self.session_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.session_list.add_css_class("navigation-sidebar")
        self.session_list.connect("row-selected", self._on_row_selected)
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

        view = Adw.ToolbarView(content=scrolled)
        view.add_top_bar(header)
        view.add_bottom_bar(run_button)
        return Adw.NavigationPage(title="Sesje", child=view)

    def _build_content(self) -> Adw.NavigationPage:
        self.view_stack = Adw.ViewStack()
        self.transcript_page = Adw.Bin()
        self.speakers_page = SpeakersPage(self.player, self.suggest_speakers, self._on_speakers_saved, self.start_task)
        self.summary_page = Adw.Bin()
        self.view_stack.add_titled_with_icon(self.transcript_page, "transcript", "Transkrypcja",
                                             "text-x-generic-symbolic")
        self.view_stack.add_titled_with_icon(self.speakers_page, "speakers", "Mówcy", "system-users-symbolic")
        self.view_stack.add_titled_with_icon(self.summary_page, "summary", "Kronika", "x-office-document-symbolic")

        self.content_header = Adw.HeaderBar(
            title_widget=Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.campaign_button = Gtk.Button(tooltip_text="Opis świata, postacie graczy i słownik nazw tej kampanii")
        self.campaign_button.connect("clicked", lambda _b: self.current and self.show_campaigns(
            self.current.campaign.key or None))
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

    def _build_task_bar(self) -> Gtk.Widget:
        self.task_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.task_title.add_css_class("heading")
        self.task_detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.task_detail.add_css_class("dim-label")
        self.task_detail.add_css_class("caption")
        self.task_progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, hexpand=True)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, width_request=320)
        labels.append(self.task_title)
        labels.append(self.task_detail)

        log_button = Gtk.Button(label="Log", action_name="win.show-log", valign=Gtk.Align.CENTER)
        cancel_button = Gtk.Button(label="Przerwij", action_name="win.cancel", valign=Gtk.Align.CENTER)
        cancel_button.add_css_class("destructive-action")

        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        box.append(labels)
        box.append(self.task_progress)
        box.append(log_button)
        box.append(cancel_button)

        self.task_revealer = Gtk.Revealer(child=box, reveal_child=False,
                                          transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        return self.task_revealer

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
        if selected in self._rows:
            self.session_list.select_row(self._rows[selected])

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

        self.transcript_page.set_child(self._transcript_view(session, transcript))
        self.speakers_page.show_session(session, transcript, keep_edits)
        self.speakers_page.set_busy(self.runner.running)
        self.summary_page.set_child(self._summary_view(session))

        if not keep_view:
            stage, _ = session_stage(session)
            page = {"czeka na transkrypcję": "transcript", "mówcy bez imion": "speakers"}.get(stage, "summary")
            if page == "summary" and not session.has_summary and not session.has_transcript:
                page = "transcript"
            self.view_stack.set_visible_child_name(page)

    def _transcript_view(self, session: Session, transcript: Transcript | None) -> Gtk.Widget:
        self.recording_panel = None
        if transcript is None:
            if session.audio_path:
                self.recording_panel = RecordingPanel(session, self.player, self.start_task,
                                                      self._register_task_button, self.runner.running)
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
        return _text_page(buffer, " · ".join(info))

    def _summary_view(self, session: Session) -> Gtk.Widget:
        if not session.has_summary:
            status = Adw.StatusPage(icon_name="x-office-document-symbolic", title="Brak kroniki")
            if session.has_transcript:
                status.set_description(f"AI ({self._provider_label()}) napisze kronikę sesji w klimacie "
                                       f"systemu {session.system_name}.")
                status.set_child(self._task_button("Generuj kronikę", lambda: self.summarize(session)))
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
        stack.add_named(_text_view(_markdown_buffer(content)), "kronika")
        stack.add_named(self._brief_view(session), "skrot")
        stack.set_visible_child_name(self._chronicle_mode)

        toggles = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        toggles.add(Adw.Toggle(label="Kronika", name="kronika"))
        toggles.add(Adw.Toggle(label="Skrót", name="skrot",
                               tooltip="Najważniejsze wydarzenia w jednym akapicie"))
        toggles.set_active_name(self._chronicle_mode)

        def toggled(group, _pspec):
            self._chronicle_mode = group.get_active_name()
            stack.set_visible_child_name(self._chronicle_mode)

        toggles.connect("notify::active-name", toggled)

        regenerate = Gtk.Button(label="Generuj ponownie")
        regenerate.connect("clicked", lambda _b: self.summarize(session, force=True))
        open_button = Gtk.Button(label="Otwórz w edytorze")
        open_button.connect("clicked", lambda _b: Gtk.FileLauncher.new(
            Gio.File.new_for_path(session.summary_path)).launch(self, None, None))
        pdf_button = Gtk.Button(label="PDF", tooltip_text="Otwórz kronikę jako PDF (utworzy go, jeśli trzeba)")
        pdf_button.connect("clicked", lambda _b: self.open_pdf(session))
        discord_button = Gtk.Button(label="Wyślij na Discord")
        discord_button.connect("clicked", lambda _b: self.show_discord(session))
        for button in (regenerate, pdf_button, discord_button):
            self._register_task_button(button)
        sent = chronicle.sent_text(session)
        info = f"{session.system_name} · " + (f"wysłano na Discord {sent}" if sent
                                               else f"{self._provider_label()} przy ponownym generowaniu")
        return _text_page(stack, info, [open_button, pdf_button, discord_button, regenerate], leading=toggles)

    def _brief_view(self, session: Session) -> Gtk.Widget:
        """Skrót kroniki (jeden akapit) albo zachęta do jego napisania."""
        def write(force: bool):
            args = ["brief", session.name, *self._provider_args()] + (["--force"] if force else [])
            self.start_task(f"Skrót kroniki {session.name}", args)

        brief = chronicle.read_brief(session)
        if not brief:
            status = Adw.StatusPage(icon_name="view-list-bullet-symbolic", title="Brak skrótu",
                                    description="AI przeczyta kronikę i opowie w jednym akapicie, co najważniejszego "
                                                "się wydarzyło - bez zbędnych szczegółów. Trwa to kilkanaście sekund.")
            status.set_child(self._task_button("Napisz skrót", lambda: write(False)))
            return status

        current = chronicle.brief_is_current(session)
        label = Gtk.Label(label="Skrót kroniki" if current else "Skrót jest starszy niż kronika - napisz go ponownie",
                          xalign=0, hexpand=True, wrap=True)
        label.add_css_class("dim-label" if current else "warning")
        again = Gtk.Button(label="Napisz ponownie", valign=Gtk.Align.CENTER)
        again.add_css_class("flat" if current else "suggested-action")
        again.connect("clicked", lambda _b: write(True))
        self._register_task_button(again)
        bar = Gtk.Box(spacing=6, margin_top=10, margin_start=24, margin_end=12)
        bar.append(label)
        bar.append(again)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(_text_view(_markdown_buffer(brief)))
        return box

    def _register_task_button(self, button: Gtk.Button) -> None:
        """Przycisk uruchamiający zadanie - nieaktywny, gdy inne zadanie jest w toku."""
        button.set_sensitive(not self.runner.running)
        self._session_task_buttons.append(button)

    def _task_button(self, label: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b: callback())
        button.set_sensitive(not self.runner.running)
        self._session_task_buttons.append(button)
        return button

    def _provider_label(self) -> str:
        return dict(PROVIDERS).get(self.provider, self.provider)

    # ------------------------------------------------------------ operacje

    def summarize(self, session: Session, force: bool = False) -> None:
        def run(allow_unnamed: bool):
            args = ["summarize", "--no-interactive", *self._provider_args()]
            if allow_unnamed:
                args.append("--allow-unnamed")
            if force:
                args.append("--force")
            self.start_task(f"Kronika {session.name}", args + [session.name])

        self._autosave_speakers()
        if not session.has_speakers and session.load_transcript().speakers:
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

    # ------------------------------------------------------------ zadania

    def start_task(self, title: str, args: list[str]) -> None:
        error = self.runner.start(title, args)
        if error:
            self.toast(error)
            return
        self._task_started = time.monotonic()
        self._proposal_counts = self._snapshot_proposals()
        self._stage_key = None
        self.task_title.set_text(title)
        self.task_detail.set_text("Uruchamianie…")
        self.task_progress.set_fraction(0)
        self._start_pulse()
        self.task_revealer.set_reveal_child(True)
        self._set_busy(True)

    def _set_busy(self, busy: bool) -> None:
        for name in TASK_ACTIONS:
            self.lookup_action(name).set_enabled(not busy)
        self.lookup_action("cancel").set_enabled(busy)
        self._session_task_buttons = [b for b in self._session_task_buttons if b.get_root() is not None]
        for button in self._session_task_buttons:
            button.set_sensitive(not busy)
        self.speakers_page.set_busy(busy)
        if self.recording_panel is not None:
            self.recording_panel.set_busy(busy)

    def _on_task_line(self, _runner, line: str) -> None:
        self.log_buffer.insert(self.log_buffer.get_end_iter(), line + "\n")
        if line.strip() and not line.startswith("$ "):
            self.task_detail.set_text(line.strip())

    def _on_task_progress(self, _runner, stage: str, session: str, fraction: float) -> None:
        key = (stage, session)
        now = time.monotonic()
        if key != self._stage_key:
            self._stage_key, self._stage_started = key, now
        label = f"{stage.capitalize()} · {session}" if session else stage.capitalize()
        if fraction < 0:
            self._start_pulse()
            self.task_detail.set_text(label + "…")
            return
        self._stop_pulse()
        self.task_progress.set_fraction(fraction)
        remaining = estimate_remaining(now - self._stage_started, fraction)
        eta = f" · zostało ok. {format_minutes(max(60, remaining))}" if remaining is not None else ""
        self.task_detail.set_text(f"{label} · {fraction:.0%}{eta}")

    def _on_task_finished(self, _runner, title: str, success: bool, description: str) -> None:
        self._stop_pulse()
        self.player.close_file()
        self.task_revealer.set_reveal_child(False)
        self._set_busy(False)
        elapsed = format_minutes(time.monotonic() - self._task_started)
        if success:
            self.toast(f"{title}: gotowe ({elapsed})")
        else:
            toast = Adw.Toast(title=f"{title}: {description}", button_label="Pokaż log", timeout=0)
            toast.connect("button-clicked", lambda _t: self.show_log())
            self.toasts.add_toast(toast)
        self.refresh(force=True)
        if self._campaigns_dialog is not None:
            self._campaigns_dialog.reload()
        if self._discord_dialog is not None:
            self._discord_dialog.reload()
        self._notify_new_proposals()
        pdf_session, self._open_pdf_after = self._open_pdf_after, None
        if success and pdf_session:
            session = next((s for s in self.sessions if s.name == pdf_session), None)
            if session is not None and chronicle.pdf_is_current(session):
                Gtk.FileLauncher.new(Gio.File.new_for_path(chronicle.pdf_path(session))).launch(self, None, None)

    def _notify_new_proposals(self) -> None:
        """Toast, gdy zadanie (kronika, „Uzupełnij z kronik”) dodało propozycje do słownika kampanii."""
        for key, count in self._snapshot_proposals().items():
            if count > self._proposal_counts.get(key, 0):
                toast = Adw.Toast(title=GLib.markup_escape_text(f"Nowe propozycje do słownika kampanii {key}: {count}"),
                                  button_label="Przejrzyj", timeout=0)
                toast.connect("button-clicked", lambda _t, k=key: self.show_campaigns(k))
                self.toasts.add_toast(toast)

    def _start_pulse(self) -> None:
        if not self._pulse_id:
            self._pulse_id = GLib.timeout_add(120, lambda: self.task_progress.pulse() or True)

    def _stop_pulse(self) -> None:
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = 0

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

    # ------------------------------------------------------------ środowisko

    def _check_environment(self) -> None:
        """W tle: czy .venv (transkrypcja, AI) działa - np. po aktualizacji systemu może wskazywać na
        odinstalowanego Pythona. Pełne sprawdzenie: ./sprawdz-srodowisko."""
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            self._show_environment_error("brak działającego interpretera w .venv")
            return
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.unsetenv("PYTHONPATH")
        try:
            process = launcher.spawnv([str(venv_python), "-c",
                                       "import faster_whisper, pyannote.audio, torchcodec.decoders"])
        except GLib.Error as e:
            self._show_environment_error(e.message)
            return

        def done(proc, result):
            try:
                _ok, output, _err = proc.communicate_utf8_finish(result)
            except GLib.Error as e:
                output = e.message
            if not proc.get_successful():
                lines = [line for line in (output or "").splitlines() if line.strip()]
                self._show_environment_error(lines[-1] if lines else "nieznany błąd")

        process.communicate_utf8_async(None, None, done)

    def _show_environment_error(self, details: str) -> None:
        self._environment_error = details
        self.env_banner.set_title("Środowisko transkrypcji (.venv) nie działa - transkrypcja, odciski głosu "
                                  "i kroniki są niedostępne")
        self.env_banner.set_revealed(True)

    def _show_environment_help(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Napraw środowisko transkrypcji",
            body="Najczęściej to skutek aktualizacji systemu (zmiana wersji Pythona). W terminalu, w katalogu "
                 f"programu ({PROJECT_ROOT}), uruchom:\n\n./sprawdz-srodowisko --napraw\n\n"
                 "Odtworzy to .venv (kilka minut, pobiera ok. 1 GB). Potem uruchom aplikację ponownie.\n\n"
                 f"Szczegóły: {self._environment_error}")
        dialog.add_response("ok", "Zamknij")
        dialog.present(self)

    def open_pdf(self, session: Session) -> None:
        """Otwiera aktualny PDF kroniki; jeśli go nie ma albo jest starszy niż kronika - najpierw go tworzy."""
        if chronicle.pdf_is_current(session):
            Gtk.FileLauncher.new(Gio.File.new_for_path(chronicle.pdf_path(session))).launch(self, None, None)
            return
        self._open_pdf_after = session.name
        self.start_task(f"PDF {session.name}", ["pdf", session.name])

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
        if self._campaigns_dialog is not None:
            self._campaigns_dialog.force_close()
        dialog = CampaignsDialog(self.start_task, lambda: self.provider, self._register_task_button, key)

        def closed(_d):
            self._campaigns_dialog = None
            self.refresh(force=True)  # zmiany w kampanii (system, imiona) widać w liście i transkrypcji

        dialog.connect("closed", closed)
        self._campaigns_dialog = dialog
        dialog.present(self)

    def _snapshot_proposals(self) -> dict[str, int]:
        counts = {}
        for path in glossary.proposals_dir().glob("*.json"):
            counts[path.stem] = glossary.count_proposals(glossary.load_proposals(path.stem))
        return counts

    def show_settings(self) -> None:
        def provider_changed(key: str) -> None:
            self.provider_action.set_state(GLib.Variant.new_string(key))

        def folders_changed() -> None:
            toast = Adw.Toast(title="Zmieniono foldery – zadziałają po ponownym uruchomieniu",
                              button_label="Uruchom ponownie", action_name="win.restart", timeout=0)
            self.toasts.add_toast(toast)

        SettingsDialog(self.provider, provider_changed, folders_changed).present(self)

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


def _icon_button(icon: str, tooltip: str, action: str) -> Gtk.Button:
    return Gtk.Button(icon_name=icon, tooltip_text=tooltip, action_name=action)


def _markdown_buffer(content: str) -> Gtk.TextBuffer:
    """Tekst kroniki/skrótu z prostym formatowaniem Markdown (nagłówki, pogrubienia, punkty)."""
    buffer = Gtk.TextBuffer()
    tags = {
        "h1": buffer.create_tag("h1", weight=Pango.Weight.BOLD, scale=1.5, pixels_below_lines=8),
        "h2": buffer.create_tag("h2", weight=Pango.Weight.BOLD, scale=1.25, pixels_above_lines=10),
        "h3": buffer.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.1, pixels_above_lines=6),
        "bold": buffer.create_tag("bold", weight=Pango.Weight.BOLD),
    }
    end = buffer.get_end_iter()
    for line in content.splitlines():
        style, spans = markdown_spans(line)
        if style == "rule":
            continue  # sekcje i tak oddzielają nagłówki
        for text, span_style in spans:
            applied = [tags[t] for t in (style, span_style) if t]
            if applied:
                buffer.insert_with_tags(end, text, *applied)
            else:
                buffer.insert(end, text)
        buffer.insert(end, "\n")
    return buffer


def _text_view(buffer: Gtk.TextBuffer) -> Gtk.Widget:
    view = Gtk.TextView(buffer=buffer, editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=18, bottom_margin=24, left_margin=24, right_margin=24, pixels_below_lines=6)
    return Gtk.ScrolledWindow(child=view, vexpand=True)


def _text_page(content: Gtk.TextBuffer | Gtk.Widget, info: str, buttons: list[Gtk.Widget] | None = None,
               leading: Gtk.Widget | None = None) -> Gtk.Widget:
    """Tekst tylko do odczytu (bufor albo gotowy widżet) z paskiem informacji i przyciskami nad nim."""
    scrolled = _text_view(content) if isinstance(content, Gtk.TextBuffer) else content

    label = Gtk.Label(label=info, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
    label.add_css_class("dim-label")
    bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=24, margin_end=12)
    if leading is not None:
        leading.set_margin_end(6)
        bar.append(leading)
    bar.append(label)
    for button in buttons or []:
        button.add_css_class("flat")
        bar.append(button)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.append(bar)
    box.append(Gtk.Separator())
    box.append(scrolled)
    return box
