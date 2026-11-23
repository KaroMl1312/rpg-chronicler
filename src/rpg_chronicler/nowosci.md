# Nowości

## 1.005 – 2026-11-23

- **Nowe okno: zakładka „Kampanie”.** Opis świata i styl obrazków, pamięć kampanii, kanał Discord, słownik z propozycjami AI, opisy i zdjęcia haseł (także obrazki od AI), „Poprzednio w kampanii…”, pomysły na sesję, notatki MG, „Zapytaj kronikarza”, encyklopedia i dzienniki postaci.
- **Naprawiono odsłuch w nowym oknie:** w wersji 1.004 przycisk ▶ nie odtwarzał nagrania.
- **Niezapisane teksty w nowym oknie nie przepadają:** imiona mówców zostają w polach, gdy w tle skończy się zadanie, a przed zamknięciem okna program zapisuje zmiany i pyta, gdy trwa zadanie (wcześniej po cichu je przerywał).
- **Bezpieczniejszy zapis kampanii w nowym oknie:** jeśli plik kampanii ma błąd po ręcznej edycji, program nie nadpisuje go, tylko pokazuje komunikat.

## 1.004 – 2026-11-23

- **Nowe okno: praca z sesją.** Doszły:
  - zakładka „Mówcy” z rozpoznawaniem graczy po głosie, sugestią AI i odsłuchem próbek głosu;
  - odsłuch cytatów;
  - „Popraw…” i cofanie poprawki kroniki;
  - wysyłka na Discord z zapowiedzią i cytatami, oznaczanie kroniki jako wysłanej;
  - sesje z notatek MG: dodawanie (Ctrl+N, przycisk „+”) i edycja notatek;
  - usuwanie kroniki albo sesji (menu „⋯” przy nazwie sesji);
  - wyszukiwarka w kronikach i transkrypcjach z odsłuchem fragmentu (Ctrl+F).

## 1.003 – 2026-11-23

- **Instalator na Windowsa (wersja testowa):** po pobraniu programu wystarczy kliknąć instaluj-windows.bat. Instalator sam pobiera Pythona, ffmpeg i biblioteki, pyta o klucze i tworzy skróty do okna programu i do konsoli z komendami. 
- **Nowe okno programu (wersja wstępna):** lekkie okno na Windowsa i Linuksa, które zastąpi dotychczasowe. Na razie ma listę sesji, transkrypcję, kronikę ze skrótem i cytatami, uruchamianie zadań z postępem, ustawienia z kluczami API i nowości. Mówcy, Discord, poprawki kroniki i zakładka Kampanie dojdą w kolejnych wersjach. Na Linuksie: ./rpg-chronicler-okno, na Windowsie: skrót „RPG Chronicles”.

## 1.002 – 2026-11-22

- **Przycinanie nagrań FLAC i WAV działa z każdą wersją ffmpeg:** w ffmpeg 8.0 (np. Ubuntu 26.04) przycinanie tych plików kończyło się błędem „Przycięte nagranie ma … zamiast …” i nagranie zostawało bez zmian. Teraz wszystkie formaty są cięte tym samym sposobem.
- **Pierwsze kroki w stronę Windowsa:** automatyczne testy sprawdzają program także na Windowsie. Polskie znaki, cudzysłowy i emoji nie psują już komunikacji z Claude Code, ffmpeg i rclone ani komunikatów programu na Windowsie. Samo okno programu (GUI) działa na razie tylko na Linuksie.

## 1.001 – 2026-11-22

- **Klucze API w ustawieniach:** nowa strona „Klucze API” w oknie ustawień. Przy każdej usłudze (Hugging Face, Claude API, Gemini, Cloudflare) są linki do stron, na których zakłada się klucz, i krótka instrukcja. Klucz zapisuje się w pliku .env i działa od razu, bez ponownego uruchamiania programu.
- **Lista nowości:** w menu jest pozycja „Nowości” z listą zmian w kolejnych wersjach.

## 1.000 – 2026-11-22

Pierwsza wersja publiczna.

- **Transkrypcja po polsku** na procesorze (faster-whisper) z rozpoznawaniem mówców (pyannote), przycinaniem ciszy i kontrolą jakości.
- **Rozpoznawanie graczy po głosie** na podstawie wcześniejszych sesji kampanii.
- **Kronika sesji od AI** (Claude Code, Claude API albo Gemini), a do tego skrót, cytaty z odsłuchem fragmentu nagrania, PDF i wysyłka na Discord ze znacznikiem, co już wysłano.
- **Kampanie:** słownik nazw z opisami i obrazkami od AI, pamięć kampanii, encyklopedia, dzienniki postaci.
- **Przed sesją:** „Poprzednio w kampanii…”, pomysły na następną sesję, notatki MG i „Zapytaj kronikarza”.
- **Sesje bez nagrania:** kronika z notatek MG.
- **Wyszukiwarka** po kronikach i transkrypcjach, statystyki sesji, poprawki kroniki poleceniem.
- **Google Drive** przez rclone: pobieranie nagrań i wysyłka gotowych plików, archiwizacja i usuwanie sesji z koszem.
