"""Okno „Wyślij na Discord”: kanał kampanii, zapowiedź (AI albo własna) i kronika w PDF jako załącznik."""
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from .. import chronicle, discord
from ..session import Session

StartTask = Callable[[str, list[str]], None]


class DiscordDialog(Adw.Dialog):
    def __init__(self, session: Session, start_task: StartTask, provider: Callable[[], str],
                 register_task_button: Callable[[Gtk.Button], None], open_campaigns: Callable[[str], None]):
        super().__init__(title="Wyślij na Discord", content_width=620, content_height=640)
        self.session = session
        self._start_task = start_task
        self._provider = provider
        self._register = register_task_button
        self._open_campaigns = open_campaigns
        self._toasts = Adw.ToastOverlay()
        self._view = Adw.ToolbarView()
        self._view.add_top_bar(Adw.HeaderBar())
        self._toasts.set_child(self._view)
        self.set_child(self._toasts)
        self.reload()

    def reload(self) -> None:
        key = self.session.campaign.key
        webhook = chronicle.webhook_for(key)
        page = Adw.PreferencesPage()
        page.add(self._channel_group(key, webhook))
        page.add(self._teaser_group())
        quotes_group = self._quotes_group()
        if quotes_group is not None:
            page.add(quotes_group)
        page.add(self._attachment_group())

        self._send = Gtk.Button(label="Wyślij", halign=Gtk.Align.CENTER, sensitive=bool(webhook))
        self._send.add_css_class("pill")
        self._send.add_css_class("suggested-action")
        self._send.connect("clicked", lambda _b: self._send_now())
        self._register(self._send)
        self._send.set_sensitive(self._send.get_sensitive() and bool(webhook))
        sent = chronicle.sent_text(self.session)
        group = Adw.PreferencesGroup(
            description=(f"Tę kronikę wysłano już {sent}. Ponowne wysłanie doda nową wiadomość na kanale."
                         if sent else "Wiadomość: tytuł kroniki, zapowiedź i PDF z całą kroniką."))
        group.add(self._send)
        page.add(group)
        self._view.set_content(page)

    # --- grupy ---

    def _channel_group(self, key: str, webhook: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Kanał")
        if webhook:
            row = Adw.ActionRow(title=f"Kanał kampanii {key}", subtitle="webhook ustawiony", use_markup=False)
            change = Gtk.Button(label="Zmień", valign=Gtk.Align.CENTER)
            change.add_css_class("flat")
            change.connect("clicked", lambda _b: (self.close(), self._open_campaigns(key)))
            row.add_suffix(change)
            group.add(row)
            return group
        group.set_description("Na Discordzie: ustawienia kanału → Integracje → Webhooki → Nowy webhook → "
                              "Kopiuj adres URL webhooka. Adres zostaje tylko na tym komputerze.")
        entry = Adw.PasswordEntryRow(title=f"Adres webhooka kanału kampanii {key}", show_apply_button=True)
        entry.connect("apply", lambda e: self._save_webhook(key, e))
        group.add(entry)
        return group

    def _save_webhook(self, key: str, entry: Adw.PasswordEntryRow) -> None:
        url = entry.get_text().strip()
        if not discord.is_valid_webhook(url):
            entry.add_css_class("error")
            self._toast("To nie jest adres webhooka Discorda (https://discord.com/api/webhooks/…)")
            return
        chronicle.set_webhook(key, url)
        self._toast("Zapisano webhook kampanii")
        self.reload()

    def _teaser_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Zapowiedź",
                                     description="2–3 zdania nad załącznikiem. Możesz ją poprawić albo napisać "
                                                 "własną; pusta - AI napisze ją przy wysyłaniu.")
        write = Gtk.Button(label="Napisz (AI)", valign=Gtk.Align.CENTER,
                           tooltip_text="AI przeczyta kronikę i napisze zapowiedź (przygotuje też PDF)")
        write.add_css_class("flat")
        write.connect("clicked", lambda _b: self._start_task(
            f"Zapowiedź {self.session.name}",
            ["discord", self.session.name, "--przygotuj", "--nowa-zapowiedz", "--provider", self._provider()]))
        self._register(write)
        group.set_header_suffix(write)

        self._teaser = Gtk.TextBuffer(text=chronicle.read_teaser(self.session))
        view = Gtk.TextView(buffer=self._teaser, wrap_mode=Gtk.WrapMode.WORD_CHAR, height_request=110,
                            top_margin=10, bottom_margin=10, left_margin=12, right_margin=12, accepts_tab=False)
        view.add_css_class("card")
        group.add(view)
        return group

    def _attachment_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Załącznik")
        current = chronicle.pdf_is_current(self.session)
        row = Adw.ActionRow(title=GLib.path_get_basename(chronicle.pdf_path(self.session)), use_markup=False,
                            subtitle="aktualny" if current else "zostanie utworzony przy wysyłaniu")
        row.add_prefix(Gtk.Image(icon_name="x-office-document-symbolic"))
        group.add(row)
        return group

    # --- wysyłka ---

    def _quotes_group(self) -> Adw.PreferencesGroup | None:
        """Przełącznik „Dołącz cytaty” (tylko gdy sesja ma cytaty)."""
        self._quotes_switch = None
        quotes = chronicle.read_quotes(self.session)
        if not quotes:
            return None
        group = Adw.PreferencesGroup(title="Cytaty sesji")
        preview = "\n".join(f"„{text}”" + (f" — {who}" if who else "") for text, who in quotes)
        self._quotes_switch = Adw.SwitchRow(title=f"Dołącz cytaty pod zapowiedzią ({len(quotes)})",
                                            subtitle=preview, subtitle_lines=0, active=True, use_markup=False)
        group.add(self._quotes_switch)
        return group

    def _send_now(self) -> None:
        text = self._teaser.get_text(self._teaser.get_start_iter(), self._teaser.get_end_iter(), False).strip()
        if text:
            chronicle.save_teaser(self.session, text)
        else:  # wyczyszczona zapowiedź - AI napisze nową
            GLib.unlink(chronicle.teaser_path(self.session))
        args = ["discord", self.session.name, "--provider", self._provider()]
        if chronicle.load_sent(self.session):
            args.append("--force")
        if self._quotes_switch is not None and not self._quotes_switch.get_active():
            args.append("--no-quotes")
        self.close()
        self._start_task(f"Wysyłanie kroniki {self.session.name} na Discord", args)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text)))
