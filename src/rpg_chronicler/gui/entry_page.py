"""Hasło słownika kampanii (postać, BN, miejsce…): dymek z opisem po najechaniu i strona z edycją opisu i zdjęcia.

Opis zapisuje się w kampanie.toml (`Campaign.with_description`), zdjęcie w TXT_DIR/obrazy/<kampania>/
(`campaigns.set_image`) - oba trafiają na Drive przy wysyłaniu. Strona zapisuje opis przy wyjściu (jak reszta
zakładki Kampanie: bez osobnego „Zapisz”), zdjęcie od razu po wybraniu.
"""
import os
from typing import Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import config
from ..campaign_tools import images
from ..campaigns import IMAGE_EXTENSIONS, image_path, remove_image, set_image

TOOLTIP_IMAGE_SIZE = 160
PAGE_IMAGE_SIZE = 280
PREVIEW_CHARS = 90
NO_DESCRIPTION = "Brak opisu - kliknij, żeby dodać opis albo zdjęcie."

_textures: dict[tuple[str, float], Gdk.Texture] = {}


def texture(path: str) -> Gdk.Texture | None:
    """Zdjęcie jako tekstura (zapamiętane dla tej wersji pliku); None, gdy nie da się go wczytać."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _textures:
        try:
            _textures[key] = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            return None
    return _textures[key]


def image_widget(path: str | None, size: int) -> Gtk.Widget | None:
    paintable = texture(path) if path else None
    if paintable is None:
        return None
    return Gtk.Image(paintable=paintable, pixel_size=size)


def preview(description: str) -> str:
    """Pierwsze słowa opisu do podtytułu wiersza."""
    text = " ".join(description.split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS - 1].rstrip() + "…"


def attach_tooltip(widget: Gtk.Widget, key: str, name: str, description: str) -> None:
    """Dymek: zdjęcie (jeśli jest), nazwa i opis - budowany dopiero przy najechaniu."""
    def query(_widget, _x, _y, _keyboard, tooltip):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=4, margin_bottom=4)
        picture = image_widget(image_path(key, name), TOOLTIP_IMAGE_SIZE)
        if picture is not None:
            box.append(picture)
        box.append(Gtk.Label(label=name, xalign=0, css_classes=["heading"]))
        box.append(Gtk.Label(label=description or NO_DESCRIPTION, xalign=0, wrap=True, max_width_chars=48))
        tooltip.set_custom(box)
        return True

    widget.set_has_tooltip(True)
    widget.connect("query-tooltip", query)


class EntryPage(Adw.NavigationPage):
    """`save(nazwa, opis)` - zapis opisu w kampanii (przy wyjściu ze strony, jeśli zmieniony);
    `generate(nazwa, wskazówki)` - zadanie „obrazek od AI” (None = bez tej opcji); `register` - przycisk zadania."""

    def __init__(self, key: str, name: str, category: str, description: str,
                 save: Callable[[str, str], None], toast: Callable[[str], None],
                 generate: Callable[[str, str], None] | None = None,
                 register: Callable[[Gtk.Widget], None] | None = None):
        super().__init__(title=name, tag=f"haslo-{key}-{name}")
        self.key, self.name = key, name
        self._save, self._toast = save, toast
        self._generate, self._register = generate, register
        self._original = description

        page = Adw.PreferencesPage()
        self.image_group = Adw.PreferencesGroup(title="Zdjęcie")
        page.add(self.image_group)
        self._image_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.image_group.add(self._image_box)

        text_group = Adw.PreferencesGroup(
            title="Opis", description=f"{category}. Krótko: kto to albo co to jest, rola w historii, "
                                      "stosunek do drużyny. Trafia do encyklopedii kampanii.")
        self.buffer = Gtk.TextBuffer(text=description)
        view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                            left_margin=12, right_margin=12, accepts_tab=False)
        view.add_css_class("card")
        text_group.add(Gtk.ScrolledWindow(child=view, min_content_height=160, hscrollbar_policy=Gtk.PolicyType.NEVER))
        page.add(text_group)

        view_root = Adw.ToolbarView(content=page)
        view_root.add_top_bar(Adw.HeaderBar())
        self.set_child(view_root)
        self.connect("hiding", lambda _p: self.save_if_changed())
        self._show_image()

    def text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False).strip()

    def save_if_changed(self) -> None:
        if self.text() != self._original.strip():
            self._original = self.text()
            self._save(self.name, self.text())

    # --- zdjęcie ---

    def refresh(self) -> None:
        """Po zadaniu z zewnątrz (np. wygenerowany obrazek)."""
        self._show_image()

    def _task_button(self, label: str, tooltip: str, callback, css: str | None = None) -> Gtk.Button:
        button = Gtk.Button(label=label, tooltip_text=tooltip, css_classes=[css] if css else [])
        button.connect("clicked", lambda _b: callback())
        if self._register is not None:
            self._register(button)
        return button

    def _start_generation(self) -> None:
        """Okienko z dodatkowymi wskazówkami (po polsku, opcjonalne), potem zadanie „image”."""
        buffer = Gtk.TextBuffer(text=images.last_hints(self.key, self.name))
        view = Gtk.TextView(buffer=buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                            left_margin=10, right_margin=10, accepts_tab=False)
        view.add_css_class("card")
        dialog = Adw.AlertDialog(
            heading=f"Obrazek: {self.name}",
            body="AI narysuje go z opisu hasła i stylu kampanii. Możesz dopisać, co ma być na obrazku - np. "
                 "„rude włosy, blizna na policzku, w deszczu, nocą”. Pisz po polsku, AI przetłumaczy; wskazówki "
                 "mają pierwszeństwo przed opisem. Puste pole = tylko opis hasła.",
            extra_child=Gtk.ScrolledWindow(child=view, min_content_height=90,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER))
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("generate", "Wygeneruj")
        dialog.set_response_appearance("generate", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("generate")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response == "generate":
                self.save_if_changed()   # zadanie czyta opis z kampanie.toml
                text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
                self._generate(self.name, " ".join(text.split()))

        dialog.connect("response", on_response)
        self.hints_dialog = dialog   # dla testu dymnego
        dialog.present(self.get_root())
        view.grab_focus()

    def _show_image(self) -> None:
        while (child := self._image_box.get_first_child()) is not None:
            self._image_box.remove(child)
        proposal = images.candidate(self.key, self.name)
        if proposal is not None:
            self._show_proposal(proposal)
            return
        path = image_path(self.key, self.name)
        picture = image_widget(path, PAGE_IMAGE_SIZE)
        if picture is not None:
            self._image_box.append(picture)
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        choose = Gtk.Button(label="Zmień zdjęcie…" if path else "Dodaj zdjęcie…",
                            tooltip_text="JPG, PNG albo WebP - kopia trafi do folderu kampanii (i na Drive)")
        choose.connect("clicked", lambda _b: self._choose_image())
        buttons.append(choose)
        if self._generate is not None and config.CLOUDFLARE_ACCOUNT_ID and config.CLOUDFLARE_API_TOKEN:
            buttons.append(self._task_button(
                "Wygeneruj obrazek (AI)", "AI narysuje obrazek z opisu w stylu kampanii (Cloudflare FLUX, "
                "darmowy limit dzienny). Najpierw zobaczysz propozycję.", self._start_generation))
        if path:
            remove = Gtk.Button(label="Usuń zdjęcie", css_classes=["destructive-action"])
            remove.connect("clicked", lambda _b: self._remove_image())
            buttons.append(remove)
        self._image_box.append(buttons)

    def _show_proposal(self, path: str) -> None:
        """Propozycja od AI: podgląd z „Zachowaj” / „Spróbuj ponownie” / „Odrzuć”."""
        self._image_box.append(Gtk.Label(label="Propozycja AI - jeszcze nie zapisana", css_classes=["dim-label"]))
        picture = image_widget(path, PAGE_IMAGE_SIZE)
        if picture is not None:
            picture.set_tooltip_text(images.prompt_for(self.key, self.name) or None)
            self._image_box.append(picture)
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        keep = Gtk.Button(label="Zachowaj", css_classes=["suggested-action"])
        keep.connect("clicked", lambda _b: self._keep_proposal())
        buttons.append(keep)
        if self._generate is not None:
            buttons.append(self._task_button("Spróbuj ponownie", "Nowa propozycja (inny obrazek z tego samego opisu)",
                                             self._start_generation))
        discard = Gtk.Button(label="Odrzuć", css_classes=["flat"])
        discard.connect("clicked", lambda _b: (images.discard_candidates(self.key, self.name), self._show_image()))
        buttons.append(discard)
        self._image_box.append(buttons)

    def _keep_proposal(self) -> None:
        try:
            images.keep_candidate(self.key, self.name)
        except (OSError, images.ImageError) as e:
            self._toast(f"Nie można zapisać obrazka: {e}")
        self._show_image()

    def _choose_image(self) -> None:
        images = Gtk.FileFilter(name="Zdjęcia (JPG, PNG, WebP)")
        for ext in IMAGE_EXTENSIONS:
            images.add_pattern(f"*{ext}")
            images.add_pattern(f"*{ext.upper()}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog = Gtk.FileDialog(title=f"Zdjęcie: {self.name}", filters=filters)

        def opened(_dialog, result):
            try:
                path = dialog.open_finish(result).get_path()
            except GLib.Error:
                return   # anulowano
            try:
                set_image(self.key, self.name, path)
            except (OSError, ValueError) as e:
                self._toast(f"Nie można dodać zdjęcia: {e}")
                return
            self._show_image()

        dialog.open(self.get_root(), None, opened)

    def _remove_image(self) -> None:
        try:
            remove_image(self.key, self.name)
        except OSError as e:
            self._toast(f"Nie można usunąć zdjęcia: {e}")
        self._show_image()
