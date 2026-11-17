"""Definicje komend i opcji CLI (argparse)."""
import argparse

from ..config import DIARIZATION_MODEL, LLM_PROVIDER, MODEL_SIZE, WHISPER_CPU_THREADS
from .audio import cmd_benchmark, cmd_silence, cmd_trim, cmd_voices
from .campaigns import cmd_glossary, cmd_memory
from .chronicles import (cmd_ask, cmd_backfill, cmd_brief, cmd_describe, cmd_diary, cmd_discord, cmd_discord_test,
                         cmd_encyclopedia, cmd_gm_notes, cmd_image, cmd_pdf, cmd_quotes, cmd_recap, cmd_revise,
                         cmd_search)
from .sessions import (cmd_add_session, cmd_archive, cmd_check, cmd_delete, cmd_fix_loops, cmd_migrate, cmd_run,
                       cmd_speakers, cmd_stats, cmd_status, cmd_summarize, cmd_sync, cmd_transcribe, cmd_upload)


PROVIDERS = ["claude-code", "anthropic", "gemini"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpg-chronicler",
        description="Transkrypcje i kroniki sesji RPG z Google Drive.",
    )
    parser.set_defaults(func=cmd_run, provider=LLM_PROVIDER, interactive=None,
                        allow_unnamed=False, offline=False)
    sub = parser.add_subparsers(title="komendy", metavar="KOMENDA")

    def sessions_arg(p, help_text):
        p.add_argument("sessions", nargs="*", metavar="SESJA", help=help_text)

    def provider_arg(p):
        p.add_argument("--provider", choices=PROVIDERS, default=LLM_PROVIDER,
                       help=f"dostawca AI (domyślnie: {LLM_PROVIDER}, z LLM_PROVIDER w .env)")

    def interactive_args(p):
        group = p.add_mutually_exclusive_group()
        group.add_argument("--interactive", dest="interactive", action="store_true", default=None,
                           help="pytaj o mówców (domyślnie, gdy uruchomione w terminalu)")
        group.add_argument("--no-interactive", dest="interactive", action="store_false",
                           help="nigdy nie pytaj (np. dla crona)")
        p.add_argument("--allow-unnamed", action="store_true",
                       help="w trybie nieinteraktywnym podsumuj też sesje bez przypisanych mówców")

    p = sub.add_parser("run", help="pełny przebieg: sync → transkrypcja → podsumowania → upload (domyślne)")
    provider_arg(p)
    interactive_args(p)
    p.add_argument("--offline", action="store_true", help="pomiń pobieranie i wysyłkę na Google Drive")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="pokaż stan sesji")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("check", help="sprawdź transkrypcje: dziury, pętle Whispera, mało tekstu, kopie sesji")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("fix-loops", help="usuń pętle Whispera (to samo zdanie wiele razy pod rząd), z kopią")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie z powtórzeniami)")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostałoby usunięte")
    p.add_argument("--undo", action="store_true", help="przywróć transkrypcję sprzed usunięcia")
    p.set_defaults(func=cmd_fix_loops)

    p = sub.add_parser("stats", help="statystyki sesji: kto ile mówił, MG a gracze, czas gry i przerw")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie z transkrypcją)")
    p.add_argument("--campaign", metavar="KAMPANIA", help="tylko sesje tej kampanii (z sumą na końcu)")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("sync", help="pobierz nagrania, transkrypcje i podsumowania z Google Drive")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("transcribe", help="transkrybuj nagrania bez transkrypcji")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("speakers", help="przypisz imiona mówcom (interaktywnie, z podpowiedzią AI)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie bez mówców)")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="przypisz ponownie, nawet jeśli mapowanie istnieje")
    p.add_argument("--suggest-only", action="store_true",
                   help="tylko zapisz sugestię AI (.mowcy-sugestia.md), bez pytania o imiona")
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("summarize", help="wygeneruj brakujące podsumowania")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    provider_arg(p)
    interactive_args(p)
    p.add_argument("--force", action="store_true", help="wygeneruj ponownie istniejące podsumowania")
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("add-session", help="dodaj sesję bez nagrania: kronika powstanie z notatek MG")
    p.add_argument("session", metavar="NAZWA", help="nazwa sesji z datą, np. Warhammer_261116 (Kampania_RRMMDD)")
    p.add_argument("--plik", dest="file", required=True, metavar="PLIK",
                   help="plik z notatkami (.txt/.md, zwykle punkty); „-” = standardowe wejście")
    p.add_argument("--obecni", dest="present", metavar="POSTACIE",
                   help="obecne postacie graczy, po przecinku (dziennik postaci, kronika)")
    p.add_argument("--replace", action="store_true", help="zastąp notatki istniejącej sesji z notatek")
    p.set_defaults(func=cmd_add_session)

    p = sub.add_parser("benchmark", help="zmierz szybkość transkrypcji na fragmencie nagrania")
    p.add_argument("session", metavar="SESJA", help="sesja z lokalnym nagraniem")
    p.add_argument("--seconds", type=int, default=300, help="długość fragmentu w sekundach (domyślnie 300)")
    p.add_argument("--offset", type=int, default=0, metavar="S",
                   help="początek fragmentu w sekundach (np. 1800 = środek sesji zamiast rozgrzewki)")
    p.add_argument("--whisper-models", nargs="+", default=[MODEL_SIZE], metavar="MODEL",
                   help=f"modele Whispera do porównania, np. medium large-v3-turbo (domyślnie {MODEL_SIZE})")
    p.add_argument("--save-text", metavar="FOLDER", help="zapisz teksty każdego modelu do porównania")
    p.add_argument("--threads", type=int, nargs="+", default=[WHISPER_CPU_THREADS],
                   help=f"liczby wątków do porównania, np. --threads 4 6 12 (domyślnie {WHISPER_CPU_THREADS})")
    p.add_argument("--vad", action="store_true", help="włącz pomijanie ciszy")
    p.add_argument("--batch-size", type=int, default=0, help="tryb wsadowy z podanym rozmiarem partii")
    p.add_argument("--no-diarization", action="store_true", help="pomiń pomiar rozpoznawania głosów")
    p.add_argument("--diarization-models", nargs="+", default=[DIARIZATION_MODEL], metavar="MODEL",
                   help=f"modele diaryzacji do porównania (domyślnie {DIARIZATION_MODEL})")
    p.add_argument("--no-whisper", dest="threads", action="store_const", const=[],
                   help="pomiń pomiar Whispera")
    p.set_defaults(func=cmd_benchmark)

    def silence_args(p):
        p.add_argument("session", metavar="SESJA", help="sesja z lokalnym nagraniem")
        p.add_argument("--noise", type=float, default=-40.0, metavar="DB",
                       help="próg ciszy w dB (domyślnie -40; wyżej, np. -35, przy szumach w tle)")
        p.add_argument("--min-silence", type=float, default=30.0, metavar="S",
                       help="najkrótsza wykrywana cisza w sekundach (domyślnie 30)")

    p = sub.add_parser("silence", help="wykryj ciszę w nagraniu i zaproponuj przycięcie")
    silence_args(p)
    p.add_argument("--force", action="store_true", help="wykryj ponownie, nawet jeśli jest zapisana analiza")
    p.set_defaults(func=cmd_silence)

    p = sub.add_parser("trim", help="przytnij ciszę na początku/końcu nagrania (oryginał trafia do oryginaly/)")
    silence_args(p)
    p.add_argument("--start", metavar="GG:MM:SS", help="początek zachowanego fragmentu (domyślnie: koniec ciszy)")
    p.add_argument("--end", metavar="GG:MM:SS", help="koniec zachowanego fragmentu (domyślnie: początek ciszy)")
    p.add_argument("--cut-gaps", type=float, default=0, metavar="MIN",
                   help="wytnij też przerwy w środku dłuższe niż MIN minut (domyślnie 0 = nie wycinaj)")
    p.add_argument("--force", action="store_true", help="przytnij mimo istniejącej transkrypcji")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż plan")
    p.set_defaults(func=cmd_trim)

    p = sub.add_parser("voices", help="policz odciski głosu mówców (do rozpoznawania graczy w kolejnych sesjach)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie bez odcisków)")
    p.add_argument("--force", action="store_true", help="policz ponownie istniejące odciski")
    p.add_argument("--no-suggest", action="store_true", help="nie pokazuj podpowiedzi imion po policzeniu")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("brief", help="napisz skrót kroniki (najważniejsze wydarzenia w jednym akapicie)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie z kroniką bez aktualnego skrótu)")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="napisz ponownie, nawet jeśli skrót jest aktualny")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("quotes", help="wybierz najlepsze cytaty z sesji (do PDF i na Discord)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie z kroniką bez cytatów)")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="wybierz ponownie, nawet jeśli cytaty są")
    p.set_defaults(func=cmd_quotes)

    p = sub.add_parser("revise", help="popraw kronikę poleceniem dla AI (np. „to nie Hans, tylko Hanna”)")
    p.add_argument("session", metavar="SESJA")
    p.add_argument("instruction", nargs="?", metavar="POLECENIE", help="co poprawić")
    provider_arg(p)
    p.add_argument("--undo", action="store_true", help="przywróć wersję sprzed ostatniej poprawki")
    p.set_defaults(func=cmd_revise)

    p = sub.add_parser("search", help="szukaj w kronikach i transkrypcjach (od najstarszej sesji)")
    p.add_argument("query", metavar="FRAZA", help="np. Ulrich albo „Ojciec Romulus” (odmiana nie przeszkadza)")
    p.add_argument("--campaign", metavar="KAMPANIA", help="tylko sesje tej kampanii")
    p.add_argument("--limit", type=int, default=50, help="najwyżej tyle wyników (domyślnie 50)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--chronicles-only", action="store_true", help="tylko kroniki")
    group.add_argument("--transcripts-only", action="store_true", help="tylko transkrypcje")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("encyclopedia", help="encyklopedia kampanii (oś czasu, stan, postacie, miejsca) w PDF")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.add_argument("--no-ai", action="store_true", help="bez opisów od AI - tylko hasła ze słownika i oś czasu")
    p.set_defaults(func=cmd_encyclopedia)

    p = sub.add_parser("recap", help="„Poprzednio w kampanii…” do przeczytania na początku sesji (opcjonalnie Discord)")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.add_argument("--discord", action="store_true", help="wyślij tekst na kanał Discord kampanii")
    p.add_argument("--force", action="store_true", help="napisz od nowa, nawet jeśli tekst jest aktualny")
    p.set_defaults(func=cmd_recap)

    p = sub.add_parser("gm-notes", help="notatki MG przed sesją: otwarte wątki, obietnice, tropy, BN-i (MD + PDF)")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.set_defaults(func=cmd_gm_notes)

    p = sub.add_parser("ask", help="zapytaj kronikarza: odpowiedź AI z kronik kampanii, ze wskazaniem sesji")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    p.add_argument("question", metavar="PYTANIE")
    provider_arg(p)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("image", help="obrazek postaci, BN-a, miejsca… od AI (Cloudflare FLUX, darmowy limit dzienny)")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    p.add_argument("name", metavar="NAZWA", help="nazwa ze słownika albo postać gracza, np. \"Sir Amos\"")
    provider_arg(p)
    p.add_argument("--zachowaj", dest="keep", action="store_true",
                   help="od razu ustaw jako zdjęcie hasła (bez tego: propozycja do przejrzenia w GUI)")
    p.add_argument("--wskazowki", dest="hints", metavar="TEKST",
                   help="dodatkowy opis po polsku, np. \"rude włosy, blizna, scena nocą\" (AI przetłumaczy)")
    p.set_defaults(func=cmd_image)

    p = sub.add_parser("describe", help="uzupełnij krótkie opisy postaci, BN-ów, miejsc… ze słownika (AI z kronik)")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("backfill", help="uzupełnij brakujące skróty, cytaty, PDF-y, encyklopedie i dzienniki postaci")
    provider_arg(p)
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostałoby uzupełnione")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("diary", help="dziennik postaci: wydarzenia kampanii z jej perspektywy (wpisy AI) w PDF")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    p.add_argument("character", metavar="POSTAĆ", help="imię postaci, np. Fen")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="napisz wszystkie wpisy od nowa (bez cache)")
    p.set_defaults(func=cmd_diary)

    p = sub.add_parser("pdf", help="zapisz kronikę jako PDF (obok kroniki, w folderze kronik)")
    p.add_argument("sessions", nargs="+", metavar="SESJA")
    p.set_defaults(func=cmd_pdf)

    p = sub.add_parser("discord", help="wyślij kronikę na kanał Discord kampanii (zapowiedź + PDF)")
    p.add_argument("session", metavar="SESJA")
    provider_arg(p)
    p.add_argument("--przygotuj", dest="prepare", action="store_true",
                   help="tylko przygotuj zapowiedź i PDF, bez wysyłania")
    p.add_argument("--nowa-zapowiedz", dest="new_teaser", action="store_true", help="napisz zapowiedź od nowa (AI)")
    p.add_argument("--force", action="store_true", help="wyślij ponownie, nawet jeśli już wysłano")
    p.add_argument("--no-quotes", action="store_true", help="bez cytatów z sesji pod zapowiedzią")
    p.set_defaults(func=cmd_discord)

    p = sub.add_parser("discord-test", help="wyślij wiadomość testową na kanał Discord kampanii")
    p.add_argument("campaign", metavar="KAMPANIA")
    p.set_defaults(func=cmd_discord_test)

    p = sub.add_parser("glossary", help="AI proponuje słownik kampanii (nazwy) na podstawie jej kronik")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.set_defaults(func=cmd_glossary)

    p = sub.add_parser("memory", help="pamięć kampanii: pokaż stan, zbuduj go z kronik (--rebuild), przyjmij propozycję")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.add_argument("--rebuild", action="store_true", help="AI buduje stan od zera ze wszystkich kronik (propozycja)")
    p.add_argument("--accept", action="store_true", help="przyjmij oczekującą propozycję AI jako stan kampanii")
    p.set_defaults(func=cmd_memory)

    p = sub.add_parser("migrate", help="zamień starsze transkrypcje .txt na format JSON")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostanie zrobione")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("archive", help="ukryj sesję: przenieś jej pliki do archiwum/ (lokalnie i na Google Drive)")
    p.add_argument("sessions", nargs="+", metavar="SESJA")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostanie przeniesione")
    p.add_argument("--offline", action="store_true", help="tylko lokalnie, bez Google Drive")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("delete", help="usuń kronikę, wszystko poza nagraniem albo całą sesję (lokalnie i z Drive)")
    p.add_argument("session", metavar="SESJA")
    p.add_argument("--zakres", dest="scope", choices=("kronika", "od-nowa", "sesja"), default="kronika",
                   help="kronika (domyślnie): kronika, skrót, cytaty, PDF…; od-nowa: wszystko poza nagraniem; "
                        "sesja: wszystko razem z nagraniem")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostanie usunięte")
    p.add_argument("--offline", action="store_true", help="tylko lokalnie (uwaga: `sync` pobierze pliki z Drive)")
    p.add_argument("--yes", action="store_true", help="bez pytania o potwierdzenie (zakres „sesja”)")
    p.add_argument("--undo", action="store_true", help="przywróć ostatnio usunięte pliki sesji z kosza")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("upload", help="wyślij transkrypcje i podsumowania na Google Drive")
    p.set_defaults(func=cmd_upload)

    return parser
