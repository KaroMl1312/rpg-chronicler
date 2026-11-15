"""Pomocniki wspólne dla komend."""
from .. import progress
from ..session import SessionNotFound, list_sessions


def audio_session(name: str):
    session = list_sessions([name])[0]
    if not session.audio_path:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma lokalnego nagrania.")
    return session


def chronicle_session(name: str):
    session = list_sessions([name])[0]
    if not session.has_summary:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma jeszcze kroniki.")
    return session


def ensure_pdf(session, force: bool = False) -> str:
    from .. import chronicle
    from ..chronicle_pdf import write_pdf
    path = chronicle.pdf_path(session)
    if force or not chronicle.pdf_is_current(session):
        progress.report("PDF", session.name)
        write_pdf(session, path)
        print(f"[SUKCES] PDF: {path}")
    return path
