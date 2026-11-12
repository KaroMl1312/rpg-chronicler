"""Okno „Kampanie”: system, opis świata, pamięć kampanii, postacie graczy, słownik nazw i propozycje AI.

Każda zmiana zapisuje się od razu do kampanie.toml (folder transkrypcji, na Drive trafia przy wysyłaniu).
"""
from dataclasses import replace as _replace
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from .. import chronicle, discord, glossary, memory
from ..campaigns import (GLOSSARY_CATEGORIES, Campaign, campaign_key, campaigns_file, default_campaign,
                         load_campaigns, update_campaign)
from ..session import list_sessions

CATEGORY_LABELS = {glossary.PLAYER_CHARACTERS: "Postacie graczy", **GLOSSARY_CATEGORIES}

StartTask = Callable[[str, list[str]], None]


class CampaignsDialog(Adw.Dialog):
    def __init__(self, start_task: StartTask, provider: Callable[[], str],
                 register_task_button: Callable[[Gtk.Button], None], initial_key: str | None = None):
        super().__init__(title="Kampanie", content_width=780, content_height=820)
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
        box.append(self._memory_group())
        box.append(self._proposals_group(campaign))
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

    def _characters_group(self, campaign: Campaign) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            title="Postacie graczy",
            description="Podpowiadane przy nazywaniu mówców; AI rozpoznaje po nich, kto jest kim. Gracz jest opcjonalny.")
        for name, player in campaign.player_characters.items():
            row = Adw.EntryRow(title=f"{name} – gracz", text=player, show_apply_button=True)
            row.connect("apply", lambda e, n=name: self._set_player(n, e.get_text().strip()))
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
                row = Adw.ActionRow(title=name, use_markup=False)
                row.add_suffix(_delete_button(f"Usuń {name}", lambda n=name: self._remove_name(category, n)))
                expander.add_row(row)
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

