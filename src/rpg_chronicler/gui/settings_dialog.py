"""Okno ustawień (Adw.PreferencesDialog). Każda zmiana zapisuje się od razu do ustawienia.toml.

Komendy CLI uruchamiane z GUI czytają ustawienia przy starcie, więc zmiany AI i transkrypcji działają
od następnego zadania. Foldery czyta też samo GUI (lista sesji) - ich zmiana wymaga ponownego uruchomienia.
"""
import os
from typing import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from .. import config, settings

PROVIDERS = [("claude-code", "Claude Code (plan Pro/Max)"), ("anthropic", "Claude API (płatne)"),
             ("gemini", "Gemini")]
CLAUDE_CODE_MODELS = [("", "Domyślny dla konta"), ("sonnet", "Sonnet"), ("opus", "Opus"), ("haiku", "Haiku")]
WHISPER_MODELS = [
    ("small", "Small", "szybki, wyraźnie mniej dokładny"),
    ("medium", "Medium", "dobry kompromis dla polskiego"),
    ("large-v3-turbo", "Large v3 Turbo", "dokładniejszy, nieco wolniejszy od Medium"),
    ("large-v3", "Large v3", "najdokładniejszy, ok. 2× wolniejszy od Medium"),
]
FOLDERS = [("foldery.nagrania", "Nagrania", config.AUDIO_DIR),
           ("foldery.transkrypcje", "Transkrypcje", config.TXT_DIR),
           ("foldery.podsumowania", "Kroniki", config.SUMMARY_DIR)]
REMOTES = [("google_drive.nagrania", "Nagrania", config.RCLONE_AUDIO_REMOTE),
           ("google_drive.transkrypcje", "Transkrypcje", config.RCLONE_TXT_REMOTE),
           ("google_drive.podsumowania", "Kroniki", config.RCLONE_SUMMARY_REMOTE)]


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, provider: str, on_provider_changed: Callable[[str], None],
                 on_folders_changed: Callable[[], None]):
        super().__init__(title="Ustawienia", search_enabled=False)
        self._values = settings.load()
        self._on_provider_changed = on_provider_changed
        self._folders_changed = False
        self.connect("closed", lambda _d: self._folders_changed and on_folders_changed())

        general = Adw.PreferencesPage(title="Ogólne", icon_name="preferences-system-symbolic")
        general.add(self._ai_group(provider))
        general.add(self._transcription_group())
        self.add(general)

        storage = Adw.PreferencesPage(title="Pliki", icon_name="folder-symbolic")
        storage.add(self._folders_group())
        storage.add(self._drive_group())
        self.add(storage)

    def _value(self, key: str, default):
        return self._values.get(key, default)

    def _save(self, key: str, value) -> None:
        try:
            self._values = settings.update({key: value})
        except OSError as e:
            self.add_toast(Adw.Toast(title=GLib.markup_escape_text(f"Nie można zapisać ustawień: {e}")))

    # --- grupy ---

    def _ai_group(self, provider: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Sztuczna inteligencja",
                                     description="Kto pisze kroniki i podpowiada, kim są mówcy.")
        group.add(self._combo("Dostawca", None, PROVIDERS, provider, self._provider_selected))
        group.add(self._combo("Model w Claude Code", "Dotyczy tylko dostawcy Claude Code", CLAUDE_CODE_MODELS,
                              self._value("ai.model_claude_code", config.CLAUDE_CODE_MODEL or ""),
                              lambda key: self._save("ai.model_claude_code", key)))
        return group

    def _provider_selected(self, key: str) -> None:
        self._save("ai.dostawca", key)
        self._on_provider_changed(key)

    def _transcription_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Transkrypcja", description="Zmiany obowiązują od następnej transkrypcji.")

        models = [(key, f"{label} – {hint}") for key, label, hint in WHISPER_MODELS]
        current_model = self._value("transkrypcja.model", config.MODEL_SIZE)
        if current_model not in dict(models):
            models.append((current_model, current_model))
        group.add(self._combo("Model Whisper", "Nowy model pobiera się przy pierwszym użyciu (do ok. 3 GB)",
                              models, current_model, lambda key: self._save("transkrypcja.model", key)))

        cpu_count = os.cpu_count() or 2
        threads = Adw.SpinRow.new_with_range(1, cpu_count, 1)
        threads.set_title("Wątki procesora")
        threads.set_subtitle(f"Zwykle najszybciej przy liczbie rdzeni fizycznych ({max(1, cpu_count // 2)}). "
                             "Sprawdzisz to komendą benchmark.")
        threads.set_value(self._value("transkrypcja.watki", config.WHISPER_CPU_THREADS))
        threads.connect("notify::value", lambda row, _p: self._save("transkrypcja.watki", int(row.get_value())))
        group.add(threads)

        vad = Adw.SwitchRow(title="Pomijanie ciszy",
                            subtitle="Szybciej przy nagraniach z długimi przerwami i mniej „zmyślonych” zdań "
                                     "w ciszy. Może czasem uciąć bardzo ciche wypowiedzi.",
                            active=self._value("transkrypcja.pomijanie_ciszy", config.WHISPER_VAD))
        vad.connect("notify::active", lambda row, _p: self._save("transkrypcja.pomijanie_ciszy", row.get_active()))
        group.add(vad)
        return group

    def _folders_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Foldery na dysku",
                                     description="Zmiana folderów wymaga ponownego uruchomienia aplikacji.")
        for key, title, default in FOLDERS:
            path = os.path.expanduser(self._value(key, default))
            row = Adw.ActionRow(title=title, subtitle=path, use_markup=False, subtitle_selectable=True)
            button = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Wybierz folder")
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, k=key, r=row: self._choose_folder(k, r))
            row.add_suffix(button)
            row.set_activatable_widget(button)
            group.add(row)
        return group

    def _choose_folder(self, key: str, row: Adw.ActionRow) -> None:
        dialog = Gtk.FileDialog(title=f"Folder: {row.get_title()}",
                                initial_folder=Gio.File.new_for_path(row.get_subtitle()))

        def on_done(dialog_, result):
            try:
                folder = dialog_.select_folder_finish(result)
            except GLib.Error:
                return  # anulowano
            path = folder.get_path()
            if path and path != row.get_subtitle():
                row.set_subtitle(path)
                self._save(key, _home_relative(path))
                self._folders_changed = True

        dialog.select_folder(self.get_root(), None, on_done)

    def _drive_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Google Drive (rclone)",
                                     description="Foldery zdalne w formacie remote:ścieżka, np. gdrive:Audio_sesje_rpg. "
                                                 "Zatwierdź zmianę przyciskiem ✓.")
        for key, title, default in REMOTES:
            row = Adw.EntryRow(title=title, text=self._value(key, default), show_apply_button=True)
            row.connect("apply", lambda r, k=key: self._apply_remote(k, r))
            group.add(row)
        return group

    def _apply_remote(self, key: str, row: Adw.EntryRow) -> None:
        text = row.get_text().strip()
        if ":" not in text:
            row.add_css_class("error")
            self.add_toast(Adw.Toast(title="Podaj folder w formacie remote:ścieżka"))
            return
        row.remove_css_class("error")
        self._save(key, text)
        self.add_toast(Adw.Toast(title="Zapisano"))

    # --- pomocnicze ---

    def _combo(self, title: str, subtitle: str | None, options: list[tuple[str, str]], current: str,
               on_selected: Callable[[str], None]) -> Adw.ComboRow:
        keys = [key for key, _ in options]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _, label in options]))
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_selected(keys.index(current) if current in keys else 0)
        row.connect("notify::selected", lambda r, _p: on_selected(keys[r.get_selected()]))
        return row


def _home_relative(path: str) -> str:
    """Zapisuje ścieżki w katalogu domowym jako ~/..., żeby plik ustawień był czytelny."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path
