"""Wspólne widżety okna głównego: strona tekstu z paskiem, Markdown, przyciski zadań, uwagi do transkrypcji."""
from typing import Callable

from gi.repository import Gtk, Pango

from .. import quality
from .text import markdown_spans

RegisterTaskButton = Callable[[Gtk.Button], None]


def icon_button(icon: str, tooltip: str, action: str) -> Gtk.Button:
    return Gtk.Button(icon_name=icon, tooltip_text=tooltip, action_name=action)


def task_button(label: str, callback: Callable[[], None], register: RegisterTaskButton) -> Gtk.Button:
    """Duży przycisk uruchamiający zadanie (np. na StatusPage) - nieaktywny, gdy inne zadanie jest w toku."""
    button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    button.add_css_class("suggested-action")
    button.connect("clicked", lambda _b: callback())
    register(button)
    return button


def issues_button(issues: list[quality.Issue]) -> Gtk.Widget:
    """Ikona ostrzeżenia z listą podejrzanych miejsc w transkrypcji (kontrola jakości)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12,
                  margin_start=12, margin_end=12)
    title = Gtk.Label(label="Podejrzane miejsca w transkrypcji", xalign=0)
    title.add_css_class("heading")
    box.append(title)
    for issue in issues:
        box.append(Gtk.Label(label=f"• {issue.message}", xalign=0, wrap=True, max_width_chars=60))
    button = Gtk.MenuButton(icon_name="dialog-warning-symbolic", popover=Gtk.Popover(child=box),
                            tooltip_text=f"Uwagi do transkrypcji: {len(issues)}")
    button.add_css_class("flat")
    button.add_css_class("warning")
    return button


def markdown_buffer(content: str) -> Gtk.TextBuffer:
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


def text_view(buffer: Gtk.TextBuffer) -> Gtk.Widget:
    view = Gtk.TextView(buffer=buffer, editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=18, bottom_margin=24, left_margin=24, right_margin=24, pixels_below_lines=6)
    return Gtk.ScrolledWindow(child=view, vexpand=True)


def text_page(content: Gtk.TextBuffer | Gtk.Widget, info: str, buttons: list[Gtk.Widget] | None = None,
              leading: Gtk.Widget | None = None) -> Gtk.Widget:
    """Tekst tylko do odczytu (bufor albo gotowy widżet) z paskiem informacji i przyciskami nad nim."""
    scrolled = text_view(content) if isinstance(content, Gtk.TextBuffer) else content

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
