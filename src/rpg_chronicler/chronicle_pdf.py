"""Kronika w PDF (Markdown → HTML → WeasyPrint). Działa w .venv (weasyprint, markdown).

Emoji są usuwane: systemowa czcionka emoji (Noto Color Emoji, format COLRv1) nie wyświetla się
w przeglądarkach PDF opartych na popplerze (np. domyślna przeglądarka GNOME) - zostawałyby puste miejsca.
"""
import html
import re

from .campaigns import campaign_key
from .chronicle import (brief_is_current, chronicle_title, read_brief, read_chronicle, read_quotes,
                        session_date_text)
from .session import Session

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿←-⇿〰〽㊗㊙]"
    "[︎️‍\U0001F3FB-\U0001F3FF]*")
HORIZONTAL_RULE_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$", re.MULTILINE)

CSS = """
@page {
    size: A4;
    margin: 2.2cm 2.3cm 2.4cm;
    @bottom-center {
        content: string(campaign) " · " counter(page) " / " counter(pages);
        font-family: 'Noto Sans', sans-serif; font-size: 8.5pt; color: #8a7a66;
    }
}
@page :first { @bottom-center { content: counter(page) " / " counter(pages); } }
html { lang: pl; }
body {
    font-family: 'Noto Serif', 'DejaVu Serif', serif; font-size: 11pt; line-height: 1.5;
    color: #2b2118; text-align: justify; hyphens: auto;
}
header { text-align: center; margin-bottom: 1.6em; padding-bottom: 1.1em; border-bottom: 1.5pt solid #8b4513; }
header .campaign {
    string-set: campaign content(); font-family: 'Noto Sans', sans-serif; font-size: 9pt;
    letter-spacing: 0.18em; text-transform: uppercase; color: #8b4513;
}
header h1 { font-size: 21pt; line-height: 1.2; margin: 0.35em 0 0.25em; text-align: center; hyphens: manual; }
header .date { font-style: italic; color: #6b5a48; }
h2, h3, h4 {
    font-family: 'Noto Sans', sans-serif; color: #7a2e12; text-align: left; hyphens: manual;
    break-after: avoid; margin: 1.5em 0 0.5em; padding-bottom: 0.15em; border-bottom: 0.5pt solid #d9c4a8;
}
h2 { font-size: 14pt; } h3 { font-size: 12.5pt; } h4 { font-size: 11.5pt; }
p { margin: 0 0 0.65em; orphans: 2; widows: 2; }
ul, ol { margin: 0 0 0.8em; padding-left: 1.3em; }
li { margin-bottom: 0.35em; }
li::marker { color: #8b4513; }
strong { color: #3d2a1a; }
blockquote { margin: 0.8em 1.5em; font-style: italic; color: #5a4a3a; }
.brief {
    background: #f6efe3; border-left: 3pt solid #8b4513; padding: 0.7em 1.1em 0.4em;
    margin: 0 0 1.6em; font-size: 10.5pt; break-inside: avoid;
}
.brief h2 {
    margin: 0 0 0.4em; padding: 0; border: none; font-size: 9pt; letter-spacing: 0.15em;
    text-transform: uppercase; color: #8b4513;
}
.brief ul { margin-bottom: 0.5em; }
.quotes { margin-top: 2em; break-inside: avoid; }
.quotes blockquote {
    margin: 0 0 0.9em; padding: 0.1em 0 0.1em 1em; border-left: 2pt solid #d9c4a8;
    font-size: 11.5pt; font-style: italic; color: #3d2a1a;
}
.quotes blockquote p { margin: 0; }
.quotes .who { margin-top: 0.15em; font-style: normal; font-size: 9.5pt; color: #8b4513; text-align: right; }
"""


def strip_emoji(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", EMOJI_RE.sub("", text))


def chronicle_html(text: str, session: Session) -> str:
    """Pełny dokument HTML kroniki. Pierwsza linia (tytuł) trafia do nagłówka strony."""
    import markdown

    text = strip_emoji(text).replace("\r\n", "\n")
    title = chronicle_title(text)
    lines = text.split("\n")
    for index, line in enumerate(lines):  # tytuł nie powtarza się w treści
        if line.strip():
            if chronicle_title(line) == title:
                lines = lines[index + 1:]
            break
    body_md = HORIZONTAL_RULE_RE.sub("", "\n".join(lines))
    body = markdown.markdown(body_md, extensions=["sane_lists"])

    campaign = session.campaign
    campaign_line = " · ".join(part for part in (campaign.system, campaign_key(session.name) or "") if part)
    if campaign.system and campaign_key(session.name) and campaign.system.casefold().startswith(
            campaign_key(session.name).casefold()):
        campaign_line = campaign.system  # „Warhammer Fantasy Roleplay · Warhammer” - bez powtórzenia
    date = session_date_text(session)
    brief = ""
    if brief_is_current(session) and read_brief(session):
        brief_body = markdown.markdown(strip_emoji(read_brief(session)), extensions=["sane_lists"])
        brief = f'<section class="brief"><h2>W skrócie</h2>{brief_body}</section>'
    quotes = quotes_html(read_quotes(session))
    return (f'<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"</head><body><header><div class=\"campaign\">{html.escape(campaign_line)}</div>"
            f"<h1>{html.escape(title)}</h1>"
            + (f'<div class="date">Sesja z {html.escape(date)}</div>' if date else "")
            + f"</header>{brief}{body}{quotes}</body></html>")


def quotes_html(quotes) -> str:
    """Sekcja „Cytaty sesji” na końcu kroniki (pusta, gdy nie ma cytatów)."""
    if not quotes:
        return ""
    items = "".join(f"<blockquote><p>„{html.escape(strip_emoji(q.text))}”</p>"
                    + (f'<div class="who">— {html.escape(q.who)}</div>' if q.who else "") + "</blockquote>"
                    for q in quotes)
    return f'<section class="quotes"><h2>Cytaty sesji</h2>{items}</section>'


def write_pdf(session: Session, path: str) -> None:
    import weasyprint

    document = chronicle_html(read_chronicle(session), session)
    tmp_path = path + ".part"
    weasyprint.HTML(string=document).write_pdf(tmp_path, stylesheets=[weasyprint.CSS(string=CSS)])
    import os
    os.replace(tmp_path, path)


def markdown_document_html(text: str, campaign_line: str) -> str:
    """Dokument HTML z Markdownu w stylu kronik: „# tytuł” i kursywa pod nim trafiają do nagłówka strony."""
    import markdown

    lines = strip_emoji(text).replace("\r\n", "\n").split("\n")
    title, subtitle = "", ""
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        title = lines.pop(0)[2:].strip()
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and lines[0].startswith("*") and lines[0].endswith("*") and not lines[0].startswith("**"):
            subtitle = lines.pop(0).strip("*").strip()
    body = markdown.markdown(HORIZONTAL_RULE_RE.sub("", "\n".join(lines)), extensions=["sane_lists"])
    return (f'<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'</head><body><header><div class="campaign">{html.escape(campaign_line)}</div>'
            f"<h1>{html.escape(title)}</h1>"
            + (f'<div class="date">{html.escape(subtitle)}</div>' if subtitle else "")
            + f"</header>{body}</body></html>")


def write_markdown_pdf(text: str, path: str, campaign_line: str) -> None:
    """PDF z dokumentu Markdown (np. encyklopedia kampanii), zapis atomowy."""
    import os

    import weasyprint

    tmp_path = path + ".part"
    weasyprint.HTML(string=markdown_document_html(text, campaign_line)).write_pdf(
        tmp_path, stylesheets=[weasyprint.CSS(string=CSS)])
    os.replace(tmp_path, path)
