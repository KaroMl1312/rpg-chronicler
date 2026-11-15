"""Komendy CLI: rpg-chronicler <komenda> [opcje]. Bez komendy uruchamia pełny przebieg (run).

Komendy są pogrupowane w modułach: sessions (przebieg), audio (nagrania), chronicles (kroniki),
campaigns (kampanie); opcje w parser.py. Ciężkie importy są leniwie wewnątrz cmd_*.
"""
import sys

from ..session import SessionNotFound, list_sessions  # noqa: F401 - list_sessions używane przez testy
from .audio import cmd_silence, cmd_trim
from .parser import PROVIDERS, build_parser  # noqa: F401
from .sessions import cmd_run  # noqa: F401 - domyślna komenda


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.interactive is None:
        args.interactive = sys.stdin.isatty()
    try:
        code = args.func(args)
    except SessionNotFound as e:
        print(f"[BŁĄD] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        from ..audio_trim import TrimError
        if not isinstance(e, (TrimError, ValueError)) or args.func not in (cmd_silence, cmd_trim):
            raise
        print(f"[BŁĄD] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return 130
    return code or 0
