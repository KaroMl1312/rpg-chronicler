# Nowości

## 1.010 – 2026-11-27

- **Prompty AI do podglądu i edycji** (menu ☰ → „Prompty AI”): wszystkie prompty programu pogrupowane według zastosowania, z opisem, kiedy są używane, i z polami do wstawienia jednym kliknięciem. Zmienione zapisują się na tym komputerze, „Przywróć domyślny” cofa zmianę, a program ostrzega, gdy usuniesz potrzebne pole albo gdy nowa wersja programu zmieni domyślny prompt.
- **Zostało jedno okno programu:** stare okno (GTK) usunięte. Wpis w menu i skrót na pulpicie tworzy teraz `./rpg-chronicler-okno --instaluj` (`--pulpit` dodaje skrót).
- **Ostrzeżenie, gdy środowisko transkrypcji nie działa** (np. po aktualizacji systemu) - pasek na górze okna z instrukcją naprawy, a gdy nie da się uruchomić nawet okna, komunikat na ekranie.

## 1.009 – 2026-11-27

- **Nowe okno wykorzystuje całą szerokość:** transkrypcja, kronika i pozostałe widoki zaczynają się od lewej i rozciągają na całe okno, jak w poprzedniej wersji, zamiast wąskiej kolumny na środku.

## 1.008 – 2026-11-27

- **Drugi sposób rozpoznawania głosów do wyboru: ONNX.** Ok. 6 razy szybszy od dotychczasowego (w próbach 7–19 minut na sesję). Wybór jest w ustawieniach, w grupie „Transkrypcja”, albo przez `transcribe --glosy onnx`. Domyślnie zostaje pyannote - porównaj podział na mówców na swoich nagraniach, zanim zmienisz.
- **Mniej pobierania przy ONNX:** jego modele zajmują ok. 33 MB i nie wymagają tokenu Hugging Face (token jest na razie nadal potrzebny do odcisków głosu).
- **Próg rozdzielania głosów dla kampanii** (Kampanie → Ogólne): gdy dwóch graczy ma podobne głosy i program łączy ich w jeden, niższy próg (np. 0,65) rozdzieli ich, kosztem kilku dodatkowych krótkich głosów do nazwania. Jednorazowo: `transcribe --prog-glosow 0.65`.

## 1.007 – 2026-11-27

- **Naprawiono transkrypcję nagrań dłuższych niż ok. 3 godziny:** rozpoznawanie głosów kończyło się na nich błędem „could not create a primitive”.

## 1.006 – 2026-11-23

- **Nowe okno: panel nagrania przed transkrypcją.** Wykrywanie ciszy z osią czasu, odsłuch granic i fragmentów ciszy, przycinanie nagrania.
- **Nowe okno: uwagi do transkrypcji** z odsłuchem podejrzanych miejsc, usuwaniem powtórzeń i cofaniem.
- **Nowe okno: statystyki** sesji i całej kampanii (kto ile mówił, MG a gracze) oraz „Uzupełnij brakujące…” w menu.
- **Poprawiony czas transkrypcji w opisie programu:** README podawał zbyt krótki, bo nie liczył rozpoznawania mówców.

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
