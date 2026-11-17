"""Wspólne widżety okna głównego: strona tekstu z paskiem, Markdown, przyciski zadań, uwagi do transkrypcji."""
from typing import Callable

from gi.repository import Gtk, Pango

from .. import chronicle, quality, stats as session_stats
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


def issues_button(issues: list[quality.Issue], actions: list[Gtk.Button] | None = None) -> Gtk.Widget:
    """Ikona ostrzeżenia z listą podejrzanych miejsc w transkrypcji (kontrola jakości).

    `actions` - przyciski pod listą (np. „Usuń powtórzenia”); kliknięcie zamyka okienko.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12,
                  margin_start=12, margin_end=12)
    title = Gtk.Label(label="Podejrzane miejsca w transkrypcji", xalign=0)
    title.add_css_class("heading")
    box.append(title)
    for issue in issues:
        box.append(Gtk.Label(label=f"• {issue.message}", xalign=0, wrap=True, max_width_chars=60))
    popover = Gtk.Popover(child=box)
    for action in actions or []:
        action.set_halign(Gtk.Align.START)
        action.connect("clicked", lambda _b: popover.popdown())
        box.append(action)
    button = Gtk.MenuButton(icon_name="dialog-warning-symbolic", popover=popover,
                            tooltip_text=f"Uwagi do transkrypcji: {len(issues)}")
    button.add_css_class("flat")
    button.add_css_class("warning")
    return button


def stats_button(stats: session_stats.SessionStats) -> Gtk.Widget:
    """„Statystyki” z okienkiem: czas gry i przerw, MG a gracze, kto ile mówił (paski udziału)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12,
                  margin_start=12, margin_end=12)
    title = Gtk.Label(label="Statystyki sesji", xalign=0)
    title.add_css_class("heading")
    box.append(title)
    fmt = session_stats.format_duration
    summary = [f"Nagranie {fmt(stats.duration)}, gra {fmt(stats.play_seconds)}, {session_stats.breaks_text(stats)}"]
    if stats.gm_seconds:
        players = sum(s.seconds for s in stats.players)
        summary.append(f"MG {stats.share(stats.gm_seconds):.0%} · gracze {stats.share(players):.0%} czasu mówienia")
    for line in summary:
        box.append(Gtk.Label(label=line, xalign=0, wrap=True, max_width_chars=50))

    grid = Gtk.Grid(column_spacing=12, row_spacing=6)
    for row, s in enumerate(stats.speakers):
        share = stats.share(s.seconds)
        grid.attach(Gtk.Label(label=s.name, xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=18),
                    0, row, 1, 1)
        bar = Gtk.ProgressBar(fraction=share, valign=Gtk.Align.CENTER, hexpand=True)
        bar.set_size_request(120, -1)
        grid.attach(bar, 1, row, 1, 1)
        detail = Gtk.Label(label=f"{share:.0%} · {session_stats.format_duration(s.seconds)}", xalign=1,
                           tooltip_text=f"{s.utterances} wypowiedzi, {s.words} słów")
        detail.add_css_class("dim-label")
        detail.add_css_class("numeric")
        grid.attach(detail, 2, row, 1, 1)
    box.append(grid)
    return Gtk.MenuButton(label="Statystyki", popover=Gtk.Popover(child=box),
                          tooltip_text="Kto ile mówił, MG a gracze, czas gry i przerw")


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


def discord_icon(session) -> Gtk.Widget:
    """Znaczek przy sesji na liście: kronika jest na Discordzie (samolot), na Discordzie starsza wersja (samolot
    ostrzegawczy) albo jej tam nie ma (puste miejsce tej samej szerokości - ikony w wierszach się nie przesuwają)."""
    state = chronicle.discord_state(session)
    if state == chronicle.NOT_SENT:
        return Gtk.Box(width_request=16, tooltip_text="Kroniki nie wysłano na Discord")
    icon = Gtk.Image(icon_name="mail-send-symbolic", tooltip_text=chronicle.discord_label(session))
    icon.add_css_class("warning" if state == chronicle.SENT_OLDER else "accent")
    return icon
