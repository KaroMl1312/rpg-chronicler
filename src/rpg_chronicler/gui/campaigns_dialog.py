"""Okno „Kampanie”: system, opis świata, pamięć kampanii, encyklopedia, dzienniki postaci, postacie graczy,
słownik nazw i propozycje AI.

Każda zmiana zapisuje się od razu do kampanie.toml (folder transkrypcji, na Drive trafia przy wysyłaniu).
"""
from dataclasses import replace as _replace
from typing import Callable

from gi.repository import Adw, Gio, GLib, Gtk

import os

from .. import ask, chronicle, diary, discord, encyclopedia, glossary, memory, prep
from ..campaigns import (GLOSSARY_CATEGORIES, Campaign, campaign_key, campaigns_file, default_campaign,
                         image_path, load_campaigns, update_campaign)
from ..session import list_sessions
from .entry_page import EntryPage, attach_tooltip, image_widget, preview

CATEGORY_LABELS = {glossary.PLAYER_CHARACTERS: "Postacie graczy", **GLOSSARY_CATEGORIES}

StartTask = Callable[[str, list[str]], None]
ASK_HISTORY_SHOWN = 5   # ostatnie pytania widoczne w oknie (historia ma ich więcej)


class CampaignsDialog(Adw.Dialog):
    def __init__(self, start_task: StartTask, provider: Callable[[], str],
                 register_task_button: Callable[[Gtk.Button], None], initial_key: str | None = None,
                 open_session: Callable[[str], None] | None = None):
        super().__init__(title="Kampanie", content_width=780, content_height=820)
        self.open_session = open_session   # przejście do kroniki sesji (np. z odpowiedzi kronikarza)
        self._start_task = start_task
        self._provider = provider
        self._register = register_task_button
        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_child(self.toasts)

        self._list_page = Adw.NavigationPage(title="Kampanie", tag="lista")
        self.nav.add(self._list_page)
        self._rebuild_list()
        if initial_key:
            self.open_campaign(initial_key, animate=False)

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))

    def reload(self) -> None:
        """Odświeża widoki po zmianie danych z zewnątrz (np. po zadaniu „Uzupełnij z kronik”)."""
        self._rebuild_list()
        page = self.nav.get_visible_page()
        if isinstance(page, CampaignPage):
            page.reload()
        elif isinstance(page, EntryPage):
            page.refresh()

    # ------------------------------------------------------------ lista kampanii

    def _rebuild_list(self) -> None:
        campaigns = load_campaigns()
        prefixes = sorted({k for s in list_sessions() if (k := campaign_key(s.name))} - set(campaigns),
                          key=str.casefold)

        content = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Kampanie",
            description="Opis świata, postacie graczy i słownik nazw trafiają do transkrypcji (poprawna pisownia) "
                        "i do kronik. Plik: " + campaigns_file())
        for key in sorted(campaigns, key=str.casefold):
            campaign = campaigns[key]
            pending = glossary.count_proposals(glossary.pending_for(campaign))
            details = [campaign.system, f"{len(campaign.all_names())} nazw"]
            if pending:
                details.append(f"{pending} propozycji AI do przejrzenia")
            if memory.load_proposal(key) is not None:
                details.append("nowy stan kampanii do przejrzenia")
            row = Adw.ActionRow(title=key, subtitle=" · ".join(details), use_markup=False, activatable=True)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, k=key: self.open_campaign(k))
            group.add(row)
        if not campaigns:
            group.add(Adw.ActionRow(title="Brak kampanii - dodaj pierwszą poniżej"))
        content.add(group)

        add_group = Adw.PreferencesGroup(
            title="Dodaj kampanię",
            description="Kampania to prefiks nazwy nagrania przed pierwszym „_”, np. Warhammer_261015 → Warhammer.")
        for prefix in prefixes:
            row = Adw.ActionRow(title=prefix, subtitle="prefiks nagrań bez kampanii", use_markup=False)
            button = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Dodaj kampanię")
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, p=prefix: self._create(p))
            row.add_suffix(button)
            add_group.add(row)
        entry = Adw.EntryRow(title="Inny prefiks", show_apply_button=True)
        entry.connect("apply", lambda e: self._create(e.get_text().strip()))
        add_group.add(entry)
        content.add(add_group)

        view = Adw.ToolbarView(content=content)
        view.add_top_bar(Adw.HeaderBar())
        self._list_page.set_child(view)

    def _create(self, key: str) -> None:
        if not key or "_" in key or "." in key or "[" in key:
            self.toast("Podaj prefiks bez „_”, np. Warhammer")
            return
        if key not in load_campaigns():
            self.save(default_campaign(key))
        self.open_campaign(key)

    def open_campaign(self, key: str, animate: bool = True) -> None:
        page = CampaignPage(self, key)
        self.nav.set_animate_transitions(animate)
        self.nav.push(page)
        self.nav.set_animate_transitions(True)

    # ------------------------------------------------------------ zapis i zadania

    def save(self, campaign: Campaign) -> bool:
        try:
            update_campaign(campaign)
        except OSError as e:
            self.toast(f"Nie można zapisać kampanii: {e}")
            return False
        self._rebuild_list()
        return True

    def start_task(self, title: str, args: list[str]) -> None:
        self._start_task(title, args)

    def start_memory(self, key: str) -> None:
        self._start_task(f"Stan kampanii {key}", ["memory", key, "--rebuild", "--provider", self._provider()])

    def start_encyclopedia(self, key: str) -> None:
        self._start_task(f"Encyklopedia kampanii {key}", ["encyclopedia", key, "--provider", self._provider()])

    def start_diary(self, key: str, character: str) -> None:
        self._start_task(f"Dziennik postaci {character}", ["diary", key, character, "--provider", self._provider()])

    def start_descriptions(self, key: str) -> None:
        self._start_task(f"Opisy haseł kampanii {key}", ["describe", key, "--provider", self._provider()])

    def start_recap(self, key: str, discord_too: bool = False) -> None:
        if discord_too:
            self._start_task(f"Poprzednio w kampanii {key} → Discord",
                             ["recap", key, "--discord", "--provider", self._provider()])
        else:
            self._start_task(f"Poprzednio w kampanii {key}", ["recap", key, "--force", "--provider", self._provider()])

    def start_gm_notes(self, key: str) -> None:
        self._start_task(f"Notatki MG {key}", ["gm-notes", key, "--provider", self._provider()])

    def start_ask(self, key: str, question: str) -> None:
        self._start_task(f"Pytanie do kronikarza ({key})", ["ask", key, question, "--provider", self._provider()])

    def start_image(self, key: str, name: str) -> None:
        self._start_task(f"Obrazek: {name}", ["image", key, name, "--provider", self._provider()])

    def start_glossary(self, key: str) -> None:
        self._start_task(f"Słownik kampanii {key}", ["glossary", key, "--provider", self._provider()])

    def register_task_button(self, button: Gtk.Button) -> None:
        self._register(button)


class CampaignPage(Adw.NavigationPage):
    def __init__(self, dialog: CampaignsDialog, key: str):
        super().__init__(title=key, tag=f"kampania-{key}")
        self.dialog = dialog
        self.key = key
        self._expanded: set[str] = set()
        self._scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        view = Adw.ToolbarView(content=self._scrolled)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self.reload()

    @property
    def campaign(self) -> Campaign:
        return load_campaigns().get(self.key) or default_campaign(self.key)

    def save(self, campaign: Campaign) -> None:
        if self.dialog.save(campaign):
            self.reload()

    def reload(self) -> None:
        """Buduje stronę od nowa, zachowując przewinięcie i rozwinięte listy."""
        position = self._scrolled.get_vadjustment().get_value()
        campaign = self.campaign
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                      margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
        box.append(self._general_group(campaign))
        box.append(self._prep_group())
        box.append(self._ask_group())
        box.append(self._memory_group())
        box.append(self._encyclopedia_group())
        box.append(self._diary_group(campaign))
        box.append(self._proposals_group(campaign))
        box.append(self._descriptions_group(campaign))
        box.append(self._characters_group(campaign))
        box.append(self._discord_group())
        for category, label in GLOSSARY_CATEGORIES.items():
            box.append(self._names_group(campaign, category, label))
        self._scrolled.set_child(Adw.Clamp(child=box, maximum_size=720))
        GLib.idle_add(lambda: self._scrolled.get_vadjustment().set_value(position) or GLib.SOURCE_REMOVE)

    # --- ogólne ---

    def _general_group(self, campaign: Campaign) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Ogólne")
        system = Adw.EntryRow(title="System RPG (styl i słownictwo kroniki)", text=campaign.system,
                              show_apply_button=True)
        system.connect("apply", lambda e: e.get_text().strip()
                       and self.save(_replace(self.campaign, system=e.get_text().strip())))
        group.add(system)

        buffer = Gtk.TextBuffer(text=campaign.context)
        view = Gtk.TextView(buffer=buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                            left_margin=12, right_margin=12, height_request=110, accepts_tab=False)
        view.add_css_class("card")
        save = Gtk.Button(label="Zapisz opis", halign=Gtk.Align.END, sensitive=False, margin_top=6)
        save.add_css_class("suggested-action")
        buffer.connect("changed", lambda b: save.set_sensitive(_buffer_text(b).strip() != self.campaign.context))
        save.connect("clicked", lambda _b: self.save(_replace(self.campaign, context=_buffer_text(buffer).strip())))

        label = Gtk.Label(label="Opis świata i kampanii dla AI (gdzie toczy się akcja, główny wątek, ton)",
                          xalign=0, wrap=True, margin_top=12, margin_bottom=6)
        label.add_css_class("dim-label")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(label)
        box.append(view)
        box.append(save)
        group.add(box)

        style = Adw.EntryRow(title="Styl obrazków AI (po angielsku; pusty - AI zaproponuje przy pierwszym obrazku)",
                             text=campaign.image_style, show_apply_button=True)
        style.set_tooltip_text("Cechy stylu, np. „grimdark fantasy, ink and watercolor, muted palette”. "
                               "Bez nazwisk artystów i nazw wydawców.")
        style.connect("apply", lambda e: self.save(_replace(self.campaign, image_style=e.get_text().strip())))
        group.add(style)
        return group

    # --- pamięć kampanii ---

    def _memory_group(self) -> Gtk.Widget:
        state, proposal = memory.load_state(self.key), memory.load_proposal(self.key)
        group = Adw.PreferencesGroup(title="Pamięć kampanii" + (" - nowa propozycja AI" if proposal else ""))
        build = Gtk.Button(label="Zbuduj z kronik", valign=Gtk.Align.CENTER,
                           tooltip_text="AI przeczyta wszystkie kroniki tej kampanii i opisze jej obecny stan")
        build.add_css_class("flat" if state or proposal else "suggested-action")
        build.connect("clicked", lambda _b: self.dialog.start_memory(self.key))
        self.dialog.register_task_button(build)
        group.set_header_suffix(build)

        shown = proposal or state
        if proposal is not None:
            group.set_description(f"AI zaktualizowało stan po sesji {proposal.session}. Popraw, co trzeba, i przyjmij "
                                  "- dopiero wtedy trafi do kolejnych kronik.")
        elif state is not None:
            after = f"po sesji {state.session}" if state.session else "wpisany ręcznie"
            group.set_description(f"Stan {after}: drużyna, zasoby, otwarte wątki i BN-i. Dostaje go AI piszące "
                                  "kronikę następnej sesji. Po każdej nowej kronice AI proponuje aktualizację.")
        else:
            group.set_description("Notatka o stanie kampanii (drużyna, zasoby, otwarte wątki, BN-i) dla AI piszącego "
                                  "kroniki. Zbuduj ją z kronik albo wpisz ręcznie; potem aktualizuje się po każdej "
                                  "nowej kronice (do zatwierdzenia).")

        buffer = Gtk.TextBuffer(text=shown.text if shown else "")
        view = Gtk.TextView(buffer=buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                            left_margin=12, right_margin=12, accepts_tab=False, monospace=True)
        view.add_css_class("card")
        scrolled = Gtk.ScrolledWindow(child=view, min_content_height=160, max_content_height=420,
                                      propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=6)
        if proposal is not None:
            reject = Gtk.Button(label="Odrzuć")
            reject.add_css_class("flat")
            reject.connect("clicked", lambda _b: self._reject_state())
            accept = Gtk.Button(label="Przyjmij")
            accept.add_css_class("suggested-action")
            accept.connect("clicked", lambda _b: self._accept_state(_buffer_text(buffer)))
            buttons.append(reject)
            buttons.append(accept)
        else:
            save = Gtk.Button(label="Zapisz stan", sensitive=False)
            save.add_css_class("suggested-action")
            original = shown.text if shown else ""
            buffer.connect("changed", lambda b: save.set_sensitive(_buffer_text(b).strip() != original))
            save.connect("clicked", lambda _b: self._save_state(_buffer_text(buffer), state))
            buttons.append(save)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6)
        box.append(scrolled)
        box.append(buttons)
        group.add(box)
        return group

    def _accept_state(self, text: str) -> None:
        try:
            memory.accept_proposal(self.key, text)
        except OSError as e:
            self.dialog.toast(f"Nie można zapisać stanu kampanii: {e}")
            return
        self.dialog.toast("Przyjęto stan kampanii")
        self.dialog.reload()

    def _reject_state(self) -> None:
        memory.discard_proposal(self.key)
        self.dialog.toast("Odrzucono propozycję stanu kampanii")
        self.dialog.reload()

    def _save_state(self, text: str, previous: memory.State | None) -> None:
        try:
            memory.save_state(self.key, text, previous.session if previous else None)
        except OSError as e:
            self.dialog.toast(f"Nie można zapisać stanu kampanii: {e}")
            return
        self.dialog.toast("Zapisano stan kampanii")
        self.reload()

    # --- encyklopedia ---

    def _encyclopedia_group(self) -> Gtk.Widget:
        pdf = encyclopedia.pdf_path(self.key)
        exists = os.path.exists(pdf)
        group = Adw.PreferencesGroup(
            title="Encyklopedia kampanii",
            description="PDF dla graczy: oś czasu sesji, stan kampanii oraz postacie, miejsca i przedmioty z opisami "
                        "(AI) i listą sesji, w których się pojawiły. Leży obok kronik, więc trafia też na Drive.")
        build = Gtk.Button(label="Odśwież" if exists else "Utwórz", valign=Gtk.Align.CENTER,
                           tooltip_text="AI przeczyta kroniki tej kampanii i opisze hasła (kilka minut)")
        build.add_css_class("flat" if exists else "suggested-action")
        build.connect("clicked", lambda _b: self.dialog.start_encyclopedia(self.key))
        self.dialog.register_task_button(build)
        group.set_header_suffix(build)
        if exists:
            modified = GLib.DateTime.new_from_unix_local(int(os.path.getmtime(pdf))).format("%d.%m.%Y %H:%M")
            row = Adw.ActionRow(title=os.path.basename(pdf), subtitle=f"utworzona {modified}", activatable=True)
            row.add_suffix(Gtk.Image(icon_name="x-office-document-symbolic"))
            row.connect("activated", lambda _r: Gtk.FileLauncher.new(Gio.File.new_for_path(pdf)).launch(
                self.get_root(), None, None))
            group.add(row)
        return group

    # --- dzienniki postaci ---

    def _diary_group(self, campaign: Campaign) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            title="Dzienniki postaci",
            description="PDF dla gracza: wydarzenia kampanii opowiedziane przez jego postać, wpis po każdej sesji "
                        "(AI, z kronik). Odświeżenie po nowej sesji dopisuje tylko nowe wpisy.")
        if not campaign.player_characters:
            group.add(Adw.ActionRow(title="Najpierw dodaj postacie graczy (niżej)", sensitive=False))
        for name in campaign.player_characters:
            pdf = diary.pdf_path(self.key, name)
            exists = os.path.exists(pdf)
            subtitle = "jeszcze nie ma"
            if exists:
                subtitle = "utworzony " + GLib.DateTime.new_from_unix_local(
                    int(os.path.getmtime(pdf))).format("%d.%m.%Y %H:%M")
            row = Adw.ActionRow(title=name, subtitle=subtitle, activatable=exists)
            if exists:
                row.add_suffix(Gtk.Image(icon_name="x-office-document-symbolic"))
                row.connect("activated", lambda _r, path=pdf: Gtk.FileLauncher.new(
                    Gio.File.new_for_path(path)).launch(self.get_root(), None, None))
            build = Gtk.Button(label="Odśwież" if exists else "Utwórz", valign=Gtk.Align.CENTER,
                               tooltip_text=f"AI opisze kolejne sesje z perspektywy postaci {name}")
            build.add_css_class("flat")
            build.connect("clicked", lambda _b, n=name: self.dialog.start_diary(self.key, n))
            self.dialog.register_task_button(build)
            row.add_suffix(build)
            group.add(row)
        return group

    # --- propozycje AI ---

    def _proposals_group(self, campaign: Campaign) -> Gtk.Widget:
        proposals = glossary.pending_for(campaign)
        count = glossary.count_proposals(proposals)
        group = Adw.PreferencesGroup(title=f"Propozycje AI ({count})" if count else "Propozycje AI")
        ask = Gtk.Button(label="Uzupełnij z kronik", valign=Gtk.Align.CENTER,
                         tooltip_text="AI przejrzy wszystkie kroniki tej kampanii i zaproponuje nowe nazwy")
        ask.add_css_class("flat" if count else "suggested-action")
        ask.connect("clicked", lambda _b: self.dialog.start_glossary(self.key))
        self.dialog.register_task_button(ask)
        group.set_header_suffix(ask)

        if not count:
            group.set_description("AI przejrzy kroniki tej kampanii i zaproponuje postacie, miejsca, przedmioty i "
                                  "inne nazwy. Po każdej nowej kronice propozycje pojawiają się tu same.")
            return group
        group.set_description("Odznacz to, czego nie chcesz w słowniku - niezaznaczone zostaną odrzucone.")

        checks: list[tuple[str, str, Gtk.CheckButton]] = []
        for category in glossary.CATEGORIES:
            names = proposals.get(category, [])
            if not names:
                continue
            expander = Adw.ExpanderRow(title=f"{CATEGORY_LABELS[category]} ({len(names)})", expanded=True)
            for name in names:
                check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
                row = Adw.ActionRow(title=name, use_markup=False, activatable_widget=check)
                row.add_prefix(check)
                expander.add_row(row)
                checks.append((category, name, check))
            group.add(expander)
        if proposals.get(glossary.DESCRIPTION):
            check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
            row = Adw.ActionRow(title="Opis świata (kampania nie ma jeszcze opisu)",
                                subtitle=proposals[glossary.DESCRIPTION], use_markup=False,
                                activatable_widget=check, subtitle_lines=0)
            row.add_prefix(check)
            group.add(row)
            checks.append((glossary.DESCRIPTION, proposals[glossary.DESCRIPTION], check))

        accept = Gtk.Button(label="Dodaj zaznaczone")
        accept.add_css_class("suggested-action")
        accept.connect("clicked", lambda _b: self._resolve(checks, accept_checked=True))
        reject = Gtk.Button(label="Odrzuć wszystkie")
        reject.add_css_class("flat")
        reject.connect("clicked", lambda _b: self._resolve(checks, accept_checked=False))
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=12)
        buttons.append(reject)
        buttons.append(accept)
        group.add(buttons)
        return group

    def _resolve(self, checks, accept_checked: bool) -> None:
        accepted: dict = {}
        handled: dict = {}
        for category, value, check in checks:
            if category == glossary.DESCRIPTION:
                handled[category] = value
                if accept_checked and check.get_active():
                    accepted[category] = value
                continue
            handled.setdefault(category, []).append(value)
            if accept_checked and check.get_active():
                accepted.setdefault(category, []).append(value)
        if accepted and not self.dialog.save(glossary.accept(self.campaign, accepted)):
            return
        glossary.remove_from_pending(self.key, handled)
        added = sum(len(v) if isinstance(v, list) else 1 for v in accepted.values())
        self.dialog.toast(f"Dodano do słownika: {added}" if added else "Odrzucono propozycje")
        self.dialog.reload()

    # --- Discord ---

    def _discord_group(self) -> Gtk.Widget:
        webhook = chronicle.webhook_for(self.key)
        group = Adw.PreferencesGroup(
            title="Discord",
            description="Kanał, na który trafiają kroniki tej kampanii. Na Discordzie: ustawienia kanału → "
                        "Integracje → Webhooki → Nowy webhook → Kopiuj adres URL. Adres zostaje tylko na tym "
                        "komputerze (nie trafia na Google Drive).")
        entry = Adw.PasswordEntryRow(title="Adres webhooka", text=webhook, show_apply_button=True)
        entry.connect("apply", lambda e: self._save_webhook(e))
        group.add(entry)
        if webhook:
            test = Gtk.Button(label="Wyślij test", valign=Gtk.Align.CENTER,
                              tooltip_text="Wyślij na kanał krótką wiadomość testową")
            test.add_css_class("flat")
            test.connect("clicked", lambda _b: self.dialog.start_task(f"Test Discorda {self.key}",
                                                                      ["discord-test", self.key]))
            self.dialog.register_task_button(test)
            remove = _delete_button("Usuń webhook", lambda: self._remove_webhook())
            buttons = Gtk.Box(spacing=6)
            buttons.append(test)
            buttons.append(remove)
            group.set_header_suffix(buttons)
        return group

    def _save_webhook(self, entry: Adw.PasswordEntryRow) -> None:
        url = entry.get_text().strip()
        if not discord.is_valid_webhook(url):
            entry.add_css_class("error")
            self.dialog.toast("To nie jest adres webhooka Discorda (https://discord.com/api/webhooks/…)")
            return
        chronicle.set_webhook(self.key, url)
        self.dialog.toast("Zapisano webhook")
        self.reload()

    def _remove_webhook(self) -> None:
        chronicle.set_webhook(self.key, None)
        self.reload()

    # --- postacie graczy ---

    # --- przed sesją: „Poprzednio w kampanii…” i notatki MG ---

    def _prep_status(self, path: str, sessions) -> str:
        after, text = prep.read(path)
        if not text:
            return "jeszcze nie napisane"
        if prep.is_current(path, self.key, sessions):
            return f"po sesji {after}"
        latest = prep.latest_session(self.key, sessions)
        return f"nieaktualne - po sesji {after}, a jest już kronika {latest.name if latest else '?'}"

    def _prep_group(self) -> Gtk.Widget:
        sessions = list_sessions()
        has_chronicles = prep.latest_session(self.key, sessions) is not None
        group = Adw.PreferencesGroup(
            title="Przed sesją",
            description="Na początek kolejnej sesji: tekst do przeczytania graczom na głos i ściągawka dla MG "
                        "(otwarte wątki, obietnice, niewykorzystane tropy, BN-i). Pisze je AI z kronik.")

        recap_file = prep.recap_path(self.key)
        _after, recap = prep.read(recap_file)
        recap_row = Adw.ExpanderRow(title=f"{prep.RECAP_TITLE}…", subtitle=self._prep_status(recap_file, sessions),
                                    enable_expansion=bool(recap), use_markup=False)
        write = Gtk.Button(label="Odśwież" if recap else "Napisz", valign=Gtk.Align.CENTER, sensitive=has_chronicles,
                           tooltip_text="AI napisze tekst z ostatniej kroniki i otwartych wątków (1–2 min czytania)")
        write.add_css_class("flat" if recap else "suggested-action")
        write.connect("clicked", lambda _b: self.dialog.start_recap(self.key))
        if has_chronicles:   # bez kronik zostaje nieaktywny (rejestracja włączałaby go po każdym zadaniu)
            self.dialog.register_task_button(write)
        recap_row.add_suffix(write)
        if recap and chronicle.webhook_for(self.key):
            send = Gtk.Button(icon_name="mail-send-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                              tooltip_text="Wyślij na kanał Discord kampanii (przed sesją)")
            send.connect("clicked", lambda _b: self._confirm_recap_discord())
            self.dialog.register_task_button(send)
            recap_row.add_suffix(send)
        if recap:
            recap_row.add_row(Gtk.Label(label=recap, wrap=True, xalign=0, selectable=True, margin_top=12,
                                        margin_bottom=12, margin_start=12, margin_end=12))
        group.add(recap_row)

        notes_md, notes_pdf = prep.gm_notes_path(self.key), prep.gm_notes_pdf_path(self.key)
        exists = os.path.exists(notes_pdf)
        notes_row = Adw.ActionRow(title="Notatki MG", subtitle=self._prep_status(notes_md, sessions),
                                  activatable=exists, use_markup=False)
        if exists:
            notes_row.add_suffix(Gtk.Image(icon_name="x-office-document-symbolic"))
            notes_row.connect("activated", lambda _r: Gtk.FileLauncher.new(Gio.File.new_for_path(notes_pdf)).launch(
                self.get_root(), None, None))
            notes_row.set_tooltip_text("Otwórz PDF z notatkami (tylko dla MG - nie trafia na Discord)")
        build = Gtk.Button(label="Odśwież" if exists else "Utwórz", valign=Gtk.Align.CENTER,
                           sensitive=has_chronicles, tooltip_text="AI przejrzy wszystkie kroniki i stan kampanii")
        build.add_css_class("flat" if exists else "suggested-action")
        build.connect("clicked", lambda _b: self.dialog.start_gm_notes(self.key))
        if has_chronicles:
            self.dialog.register_task_button(build)
        notes_row.add_suffix(build)
        group.add(notes_row)
        return group

    def _confirm_recap_discord(self) -> None:
        dialog = Adw.AlertDialog(heading=f"Wysłać „{prep.RECAP_TITLE}…” na Discord?",
                                 body=f"Tekst trafi na kanał kampanii {self.key} - zobaczą go gracze.")
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("send", "Wyślij")
        dialog.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _d, r: r == "send" and self.dialog.start_recap(self.key, discord_too=True))
        dialog.present(self.get_root())

    # --- zapytaj kronikarza ---

    def _ask_group(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            title="Zapytaj kronikarza",
            description="Pytanie o kampanię, np. „Kiedy poznaliśmy Ojca Romulusa?” albo „Komu jesteśmy winni "
                        "pieniądze?”. AI odpowie z kronik i stanu kampanii i wskaże sesje.")
        has_chronicles = prep.latest_session(self.key, list_sessions()) is not None
        entry = Adw.EntryRow(title="Twoje pytanie" if has_chronicles else "Twoje pytanie (najpierw potrzebna kronika)",
                             show_apply_button=True, sensitive=has_chronicles)
        entry.connect("apply", lambda e: e.get_text().strip() and self.dialog.start_ask(self.key, e.get_text().strip()))
        if has_chronicles:
            self.dialog.register_task_button(entry)
        group.add(entry)
        for index, item in enumerate(ask.load_history(self.key)[:ASK_HISTORY_SHOWN]):
            row = Adw.ExpanderRow(title=item.question, subtitle=item.asked.replace("T", " "), use_markup=False,
                                  expanded=index == 0)
            row.add_suffix(_delete_button("Usuń z historii", lambda i=index: self._forget_answer(i)))
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12,
                              margin_start=12, margin_end=12)
            content.append(Gtk.Label(label=item.answer, wrap=True, xalign=0, selectable=True))
            if item.sessions and self.dialog.open_session is not None:
                links = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4)
                for name in item.sessions:
                    link = Gtk.Button(label=name, css_classes=["flat"], tooltip_text="Przejdź do kroniki tej sesji")
                    link.connect("clicked", lambda _b, n=name: self.dialog.open_session(n))
                    links.append(link)
                content.append(links)
            row.add_row(content)
            group.add(row)
        return group

    def _forget_answer(self, index: int) -> None:
        ask.remove_from_history(self.key, index)
        self.reload()

    # --- opisy haseł (dymek, strona z edycją i zdjęciem) ---

    def _descriptions_group(self, campaign: Campaign) -> Gtk.Widget:
        names = campaign.all_names()
        described = sum(1 for n in names if campaign.description(n))
        group = Adw.PreferencesGroup(
            title="Opisy haseł",
            description=f"Krótki opis postaci, BN-ów, miejsc i przedmiotów ze słownika poniżej - najedź na "
                        f"nazwę, żeby go zobaczyć, kliknij, żeby edytować i dodać zdjęcie. "
                        f"Opisane: {described} z {len(names)}.")
        if names and described < len(names):
            fill = Gtk.Button(label="Uzupełnij z kronik", valign=Gtk.Align.CENTER,
                              tooltip_text="AI opisze nazwy bez opisu na podstawie kronik (te same opisy co "
                                           "w encyklopedii); opisów wpisanych ręcznie nie zmienia")
            fill.add_css_class("flat")
            fill.connect("clicked", lambda _b: self.dialog.start_descriptions(self.key))
            self.dialog.register_task_button(fill)
            group.set_header_suffix(fill)
        return group

    def open_entry(self, name: str, category: str) -> None:
        def save(entry_name: str, text: str) -> None:
            self.save(self.campaign.with_description(entry_name, text))
            self.dialog.toast(f"Zapisano opis: {entry_name}")

        campaign = self.campaign
        entry = EntryPage(self.key, name, category, campaign.description(name), save, self.dialog.toast,
                          generate=lambda n: self.dialog.start_image(self.key, n),
                          register=self.dialog.register_task_button)
        entry.connect("hidden", lambda _p: self.reload())   # miniatury i opisy na liście
        self.dialog.nav.push(entry)

    def _entry_row(self, campaign: Campaign, name: str, category: str, delete: Gtk.Widget) -> Adw.ActionRow:
        """Wiersz nazwy: podgląd opisu, miniatura zdjęcia, dymek z pełnym opisem; kliknięcie - strona hasła."""
        description = campaign.description(name)
        row = Adw.ActionRow(title=name, subtitle=preview(description), use_markup=False, activatable=True,
                            subtitle_lines=1)
        thumbnail = image_widget(image_path(self.key, name), 32)
        if thumbnail is not None:
            row.add_prefix(thumbnail)
        attach_tooltip(row, self.key, name, description)
        row.connect("activated", lambda _r: self.open_entry(name, category))
        row.add_suffix(delete)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic", css_classes=["dim-label"]))
        return row

    def _characters_group(self, campaign: Campaign) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            title="Postacie graczy",
            description="Podpowiadane przy nazywaniu mówców; AI rozpoznaje po nich, kto jest kim. Gracz jest opcjonalny.")
        for name, player in campaign.player_characters.items():
            row = Adw.EntryRow(title=f"{name} – gracz", text=player, show_apply_button=True)
            row.connect("apply", lambda e, n=name: self._set_player(n, e.get_text().strip()))
            info = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
            attach_tooltip(info, self.key, name, campaign.description(name))
            info.connect("clicked", lambda _b, n=name: self.open_entry(n, "Postać gracza"))
            row.add_suffix(info)
            row.add_suffix(_delete_button(f"Usuń postać {name}", lambda n=name: self._remove_character(n)))
            group.add(row)
        add = Adw.EntryRow(title="Dodaj postać (np. „Fen” albo „Fen = Ania”)", show_apply_button=True)
        add.connect("apply", lambda e: self._add_character(e.get_text()))
        group.add(add)
        return group

    def _set_player(self, name: str, player: str) -> None:
        characters = dict(self.campaign.player_characters)
        characters[name] = player
        self.save(_replace(self.campaign, player_characters=characters))

    def _remove_character(self, name: str) -> None:
        characters = {k: v for k, v in self.campaign.player_characters.items() if k != name}
        self.save(_replace(self.campaign, player_characters=characters))

    def _add_character(self, text: str) -> None:
        name, _, player = text.partition("=")
        name, player = name.strip(), player.strip()
        if not name:
            return
        characters = dict(self.campaign.player_characters)
        characters[name] = player or characters.get(name, "")
        self.save(_replace(self.campaign, player_characters=characters))

    # --- słownik ---

    def _names_group(self, campaign: Campaign, category: str, label: str) -> Gtk.Widget:
        names = campaign.names(category)
        group = Adw.PreferencesGroup(title=label)
        add = Adw.EntryRow(title="Dodaj (kilka nazw oddziel przecinkami)", show_apply_button=True)
        add.connect("apply", lambda e: self._add_names(category, e.get_text()))
        group.add(add)
        if names:
            preview = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
            expander = Adw.ExpanderRow(title=f"Nazwy ({len(names)})", subtitle=preview, use_markup=False,
                                       expanded=category in self._expanded)
            expander.connect("notify::expanded", lambda e, _p: (self._expanded.add if e.get_expanded()
                                                                 else self._expanded.discard)(category))
            for name in names:
                delete = _delete_button(f"Usuń {name}", lambda n=name: self._remove_name(category, n))
                expander.add_row(self._entry_row(campaign, name, label, delete))
            group.add(expander)
        return group

    def _add_names(self, category: str, text: str) -> None:
        new = [n.strip() for n in text.split(",") if n.strip()]
        if new:
            self._expanded.add(category)
            self.save(self.campaign.with_names(category, [*self.campaign.names(category), *new]))

    def _remove_name(self, category: str, name: str) -> None:
        self.save(self.campaign.with_names(category, [n for n in self.campaign.names(category) if n != name]))


def _delete_button(tooltip: str, callback) -> Gtk.Button:
    button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    button.add_css_class("flat")
    button.connect("clicked", lambda _b: callback())
    return button


def _buffer_text(buffer: Gtk.TextBuffer) -> str:
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

