# Nowości

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
