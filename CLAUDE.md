# CLAUDE.md — rpg-chronicler

Opis projektu dla modelu AI pracującego w tym repozytorium. Kod, komentarze, komunikaty CLI i commity są **po polsku** — trzymaj się tego.

## Cel aplikacji

`rpg-chronicler` to CLI, które:
1. pobiera nagrania sesji RPG z Google Drive (przez `rclone`),
2. transkrybuje je lokalnie na CPU (faster-whisper, model `medium`, język `pl`) z rozpoznawaniem mówców (pyannote),
3. pozwala przypisać etykietom `SPEAKER_XX` imiona/role (z podpowiedzią LLM),
4. generuje klimatyczne „kroniki sesji” przez LLM (Claude Code / API Anthropic / Gemini),
5. wysyła transkrypcje i podsumowania z powrotem na Google Drive.

Ma też GUI (GTK4 + libadwaita) — patrz sekcja „GUI”.

## Uruchamianie i testy

Projekt ma własne środowisko `.venv` na **Pythonie 3.11** (systemowy `python` to 3.15, a dla niego nie ma `onnxruntime`, którego wymaga faster-whisper). Torch, torchaudio i **torchcodec** muszą być w wersji **CPU** z indeksu PyTorch — zwykły `pip install` ściąga wersje z CUDA (~4 GB więcej), a torchcodec z PyPI wymaga bibliotek CUDA (`libnvrtc`) i bez nich pyannote nie odczyta plików. Zawsze używaj `.venv/bin/...`:

```bash
./sprawdz-srodowisko                     # sprawdza GUI, .venv, narzędzia i konfigurację (np. po aktualizacji Fedory)
./sprawdz-srodowisko --napraw            # odtwarza .venv: python3.11, torch/torchaudio/torchcodec CPU, potem -e .[dev,anthropic,gemini]
.venv/bin/rpg-chronicler                 # = rpg-chronicler run (sync → transkrypcja → podsumowania → upload)
.venv/bin/python -m rpg_chronicler status
.venv/bin/python -m pytest               # testy (szybkie, bez modeli i sieci; z testem dymnym GUI w Broadway)
.venv/bin/python -m pytest -m "not gui"  # bez testu GUI
./rpg-chronicler-gui                     # GUI (systemowy Python, patrz niżej)
./rpg-chronicler-gui --instaluj          # wpis w menu aplikacji (~/.local/share); --pulpit dodaje skrót na pulpicie; --odinstaluj usuwa
```

Komendy (pakiet `src/rpg_chronicler/cli/`, opcje w `cli/parser.py`): `run [--offline]`, `status`, `sync`, `transcribe`, `speakers [--suggest-only]`, `summarize [--force] [--allow-unnamed]`, `add-session NAZWA --plik PLIK [--obecni "A, B"] [--replace]`, `benchmark SESJA`, `voices [SESJA...] [--force]`, `brief [SESJA...] [--force]`, `quotes [SESJA...] [--force]`, `pdf SESJA...`, `discord SESJA [--przygotuj] [--nowa-zapowiedz] [--force] [--no-quotes] [--oznacz|--odznacz]`, `discord-test KAMPANIA`, `glossary KAMPANIA`, `memory KAMPANIA [--rebuild] [--accept]`, `revise SESJA "POLECENIE" [--undo]`, `search FRAZA [--campaign K] [--chronicles-only|--transcripts-only]`, `encyclopedia KAMPANIA [--no-ai]`, `describe KAMPANIA`, `recap KAMPANIA [--discord] [--force]`, `ideas KAMPANIA`, `gm-notes KAMPANIA`, `ask KAMPANIA "PYTANIE"`, `image KAMPANIA "NAZWA" [--zachowaj] [--wskazowki TEKST]`, `diary KAMPANIA POSTAĆ [--force]`, `stats [SESJA...] [--campaign K]`, `silence SESJA`, `trim SESJA [--start] [--end] [--cut-gaps MIN] [--dry-run]`, `check [SESJA...]`, `fix-loops [SESJA...] [--dry-run] [--undo]`, `backfill [--dry-run]`, `archive SESJA... [--dry-run] [--offline]`, `delete SESJA [--zakres kronika|od-nowa|sesja] [--dry-run] [--offline] [--yes] [--undo]`, `migrate [--dry-run]`, `upload`. Większość przyjmuje opcjonalną listę nazw sesji; `--provider` wybiera LLM; `--interactive/--no-interactive` (domyślnie: czy stdin to TTY — dla crona tryb nieinteraktywny).

## Struktura

```
kampanie.przyklad.toml        # przykład formatu; właściwy plik kampanii jest w TXT_DIR (patrz „Kampanie”)
.env / .env.example           # sekrety: HUGGINGFACE_TOKEN, GEMINI_API_KEY, ANTHROPIC_API_KEY, LLM_PROVIDER, CLOUDFLARE_*
src/rpg_chronicler/
  config.py                   # WSZYSTKIE stałe: ścieżki, remote'y rclone, modele, wątki, retry; własny loader .env
  settings.py                 # ustawienia użytkownika ~/.config/rpg-chronicler/ustawienia.toml (z GUI)
  cli/                        # komendy: __init__ (main), parser (argparse), common (pomocniki), sessions (przebieg),
                              #   audio (nagrania), chronicles (kroniki, PDF, Discord, szukanie), campaigns; ciężkie importy leniwie w cmd_*
  session.py                  # Session (nazwa + ścieżki pochodne), list_sessions(), SessionNotFound
  notes.py                    # sesje bez nagrania: notatki MG (<nazwa>.notatki.md), obecni, nazwa sesji, adnotacja; stdlib
  campaigns.py                # Campaign (system, opis, postacie graczy, słownik), odczyt/zapis kampanie.toml, session_date()
  voices.py                   # odciski głosu (.glosy.json), profile głosów kampanii, podpowiedzi imion; tylko stdlib
  transcript.py               # Segment, Transcript (JSON ⇄ .txt), compact_for_llm(), mapowanie mówców
  speakers.py                 # identify_speakers(): sugestia LLM + input() użytkownika
  summary.py                  # name_speakers(), summarize_sessions() - tylko kronika
  context.py                  # kontekst dla AI: speaker_mapping_info, previous_session, campaign_context
  chronicle_events.py         # kronika w dwóch krokach: części, lista wydarzeń (cache), chronicle_source
  after_chronicle.py          # dodatki po kronice: skrót, cytaty, propozycje słownika i stanu kampanii (run_all)
  revision.py                 # poprawka kroniki poleceniem (revise_chronicle)
  textmatch.py                # dopasowanie słów odporne na polską odmianę (początki słów, ruchome „e”); stdlib
  search.py                   # wyszukiwarka po kronikach i transkrypcjach (od najstarszej sesji); stdlib
  stats.py                    # statystyki sesji: kto ile mówił, MG a gracze, czas gry i przerw; stdlib
  quality.py                  # kontrola jakości transkrypcji: mało tekstu, dziury, pętle Whispera (i ich usuwanie), kopie; stdlib
  audio_trim.py               # wykrywanie ciszy (ffmpeg silencedetect) i przycinanie nagrań; tylko stdlib + ffmpeg
  chronicle.py                # kronika do udostępnienia: tytuł, data sesji, zapowiedź, stan wysyłki, webhooki; stdlib
  chronicle_pdf.py            # PDF kroniki (markdown → HTML → WeasyPrint, CSS w module); tylko .venv
  discord.py                  # wysyłka przez webhook (urllib, multipart z PDF); stdlib
  doctor.py                   # ./sprawdz-srodowisko: diagnostyka i naprawa .venv (systemowy Python, tylko stdlib)
  progress.py                 # protokół postępu dla GUI: linie `@@postep {json}` gdy RPG_CHRONICLER_PROGRESS=json
  gui/                        # GTK4 + libadwaita, uruchamiane systemowym Pythonem (skrypt ./rpg-chronicler-gui)
    app.py, window.py         #   Adw.Application, główne okno: przełącznik Sesje/Kampanie (Ctrl+1 / Ctrl+K), lista sesji (z filtrem kampanii), zakładki sesji, zadania
    transcript_page.py        #   zakładka „Transkrypcja”: tekst z kolorami mówców + uwagi jakości albo panel nagrania
    chronicle_page.py         #   zakładka „Kronika”: kronika / skrót, PDF, Discord, ponowne generowanie
    task_bar.py               #   pasek zadania na dole (etap, postęp, szacowany czas)
    environment.py            #   baner „.venv nie działa” (sprawdzenie w tle przy starcie)
    widgets.py                #   wspólne widżety: text_page, markdown_buffer, task_button, issues_button
    speakers_page.py          #   zakładka „Mówcy”: sugestia AI, imiona, odsłuch próbek
    discord_dialog.py         #   okno „Wyślij na Discord”: kanał, zapowiedź (edytowalna/AI), załącznik PDF
    campaigns_view.py         #   zakładka „Kampanie”: lista kampanii + strona kampanii z podzakładkami Ogólne / Słownik / Przed sesją / Dokumenty
    notes_dialog.py           #   okno „Dodaj sesję z notatek” (Ctrl+N): kampania, data, obecni, notatki; też edycja notatek
    entry_page.py             #   hasło słownika: dymek z opisem i miniaturą, strona z edycją opisu i zdjęciem
    search_dialog.py          #   okno „Szukaj w sesjach” (Ctrl+F): wyniki z pogrubieniem, odsłuch fragmentu, przejście do sesji
    recording_page.py         #   panel nagrania przed transkrypcją: cisza, oś czasu, przycinanie, „Transkrybuj”
    settings_dialog.py        #   okno ustawień (Adw.PreferencesDialog), zapis od razu przy zmianie
    desktop.py                #   APP_ID, instalacja .desktop + ikony (pl.rpgchronicler.Kronikarz.svg)
    tasks.py                  #   TaskRunner: uruchamia .venv/bin/rpg-chronicler (Gio.Subprocess), czyta postęp
    player.py                 #   SnippetPlayer: odsłuch fragmentu nagrania (Gtk.MediaFile/GStreamer)
    text.py                   #   logika bez GTK (stan sesji, formatowanie, Markdown, nowe propozycje AI) - testowana pytestem
  prompts/                    # szablony .md + render(name, **pola) (str.format → klamry trzeba podwajać)
  llm/                        # LLMClient (Protocol), LLMError(retryable), with_retry, get_client(provider)
    claude_code.py            #   `claude -p` w podprocesie (plan Pro/Max), bez narzędzi i MCP, cwd=tempdir
    anthropic_api.py          #   SDK anthropic, streaming, effort, server-side fallback (beta)
    gemini.py                 #   google-genai, wymuszony odstęp między zapytaniami
  transcription/
    runner.py                 # load_whisper/load_diarization/diarize/transcribe_audio, transcribe_sessions()
    merge.py                  # assign_speakers(): segment → mówca o największym pokryciu (wskaźnik przesuwny)
    benchmark.py              # pomiar szybkości na fragmencie nagrania
    voiceprints.py            # liczenie odcisków głosu (pyannote/wespeaker) z nagrania i czasów z transkrypcji
  campaign_tools/             # funkcje kampanii (zakładka Kampanie); __init__ bez importów - GUI importuje część modułów
    memory.py                 #   pamięć kampanii: stan-kampanii-<kampania>.md + propozycje AI w ~/.cache/rpg-chronicler/stan-kampanii/
    glossary.py               #   propozycje słownika od AI z kronik, oczekujące w ~/.cache/rpg-chronicler/kampanie/
    encyclopedia.py           #   encyklopedia kampanii: oś czasu, stan, hasła z opisami AI → .md + PDF
    diary.py                  #   dziennik postaci: wpis AI o każdej sesji z jej perspektywy (cache) → .md + PDF
    prep.py                   #   przed sesją: „Poprzednio w kampanii…” (recap), pomysły na sesję (ideas) i notatki MG; stdlib
    ask.py                    #   „Zapytaj kronikarza”: odpowiedź AI z kronik ze wskazaniem sesji, historia pytań; stdlib
    images.py                 #   obrazki haseł od AI: prompt z opisu (LLM) → Cloudflare FLUX → propozycja → zdjęcie; urllib
  maintenance/                # porządki; __init__ bez importów
    archive.py                #   archiwizacja sesji do podfolderów archiwum/ (lokalnie; Drive w storage/drive.py); stdlib
    deletion.py               #   usuwanie: kronika / wszystko poza nagraniem / cała sesja; kosz aplikacji, przywracanie; stdlib
    backfill.py               #   „Uzupełnij brakujące”: plan skrótów, cytatów, PDF-ów, encyklopedii, dzienników; stdlib
  storage/drive.py            # rclone copy w obie strony
tests/                        # pytest; conftest.py: HOME/XDG_* zawsze w tmp (autouse), fixture `workspace` (tmp katalogi + FakeLLM, cache w tmp, propozycje słownika wyłączone)
```

## Model danych i konwencje plików

**Sesja** = jedno nagranie identyfikowane nazwą pliku bez rozszerzenia, np. `Warhammer_261015`. Prefiks przed pierwszym `_` to klucz kampanii w `kampanie.toml` (brak sekcji → system = prefiks; brak `_` → system „RPG”).

Pliki (katalogi lokalne z `config.py`, domyślnie w `~/Documents/`):

| Plik | Katalog | Opis |
|---|---|---|
| `<nazwa>.m4a/.mp3/.wav/.flac/.ogg` | `AUDIO_DIR` | nagranie |
| `<nazwa>.transkrypcja.json` | `TXT_DIR` | **źródło prawdy** transkrypcji (`Transcript.to_dict`, `version=1`) |
| `<nazwa>.txt` | `TXT_DIR` | wersja do czytania, generowana z JSON; starsze sesje mają tylko .txt |
| `<nazwa>.mowcy.json` | `TXT_DIR` | mapowanie `{"SPEAKER_00": "MG", ...}` |
| `<nazwa>.notatki.md` | `TXT_DIR` | sesja bez nagrania: notatki MG zamiast transkrypcji; 1. linia opcjonalnie `<!-- obecni: A, B -->` |
| `<nazwa>.mowcy-sugestia.md` | `TXT_DIR` | ostatnia sugestia AI co do mówców (`.md`, żeby nie była brana za transkrypcję) |
| `<nazwa>_podsumowanie.txt` | `SUMMARY_DIR` | kronika wygenerowana przez LLM |
| `<nazwa>.glosy.json` | `TXT_DIR` | odciski głosu mówców (wektory wespeaker) do rozpoznawania graczy |
| `<nazwa>_skrot.txt` | `SUMMARY_DIR` | skrót kroniki: jeden akapit opowieści o najważniejszych wydarzeniach (AI) |
| `<nazwa>_cytaty.txt` | `SUMMARY_DIR` | cytaty z sesji (po jednym na postać + 2–3 najciekawsze), linie `[0:05:34–0:05:44] „cytat” — Postać` (czas = fragment nagrania do odsłuchu, opcjonalny; AI, można poprawiać ręcznie) |
| `<nazwa>_zapowiedz.txt`, `_kronika.pdf`, `_discord.json` | `SUMMARY_DIR` | zapowiedź na Discord, PDF kroniki, kiedy wysłano (`recznie: true` = oznaczone bez wysyłania) |
| `stan-kampanii-<kampania>.md` | `TXT_DIR` | pamięć kampanii (zatwierdzona), 1. linia `<!-- po sesji: NAZWA -->` |
| `<nazwa>_wydarzenia.md` | `SUMMARY_DIR` | lista wydarzeń z części transkrypcji (krok pośredni kroniki w dwóch krokach) |
| `encyklopedia-<kampania>.md`, `.pdf` | `SUMMARY_DIR` | encyklopedia kampanii (komenda `encyclopedia`, przycisk w zakładce Kampanie) |
| `dziennik-<kampania>-<postać>.md`, `.pdf` | `SUMMARY_DIR` | dziennik postaci (komenda `diary`, zakładka Kampanie); spacje w imieniu → `_` |
| `poprzednio-<kampania>.md` | `SUMMARY_DIR` | „Poprzednio w kampanii…” (`recap`), 1. linia `<!-- po sesji: NAZWA -->` |
| `pomysly-<kampania>.md` | `SUMMARY_DIR` | pomysły na wydarzenia najbliższej sesji (`ideas`), nagłówek jak wyżej; tylko dla MG |
| `notatki-mg-<kampania>.md`, `.pdf` | `SUMMARY_DIR` | notatki MG przed sesją (`gm-notes`), nagłówek jak wyżej; nie trafiają na Discord |
| `kampanie.toml` | `TXT_DIR` | kampanie: system, opis świata, postacie graczy, słownik nazw, opisy haseł `[K.opisy]` (synchronizowany z Drive) |
| `obrazy/<kampania>/<nazwa>.jpg/.png/.webp` | `TXT_DIR` | zdjęcia haseł (postacie, BN-i, miejsca…); nazwa pliku = nazwa hasła małymi literami, `_` zamiast spacji |

Format linii .txt: `[SPEAKER_00] [12.34s -> 15.67s] tekst` lub (stare, bez mówców) `[12.34s -> 15.67s] tekst`. `load_transcript` preferuje JSON, a w razie braku parsuje .txt. Komenda `migrate` tworzy JSON z .txt, nie ruszając .txt.

**Przycinanie ciszy** (`silence`/`trim`, panel w zakładce Transkrypcja przed transkrypcją): analiza zapisuje się w `~/.cache/rpg-chronicler/cisza/<nazwa>.json` (ważna, dopóki nie zmieni się rozmiar/data pliku nagrania). `trim` zastępuje nagranie przyciętą wersją, a oryginał przenosi do `AUDIO_DIR/oryginaly/` (`list_sessions` nie widzi podfolderów ani ukrytych plików tymczasowych `.<nazwa>.przycinanie.*`). AAC/MP3 są cięte bez kodowania (concat + `-c copy`), formaty bezstratne filtrem `aselect` tym samym kodekiem — **nie** używaj `-c copy` dla FLAC (zostaje stary nagłówek, cięcie nie działa) ani wielu gałęzi `atrim` (buforują gigabajty przy długich plikach). `trim` odmawia, gdy sesja ma już transkrypcję (czasy by się rozjechały), chyba że `--force`. Nagrania z dyktafonów bywają FLAC-ami **bez długości w nagłówku**: `ffprobe` nie zwraca `duration` (wtedy `audio_trim.probe` mierzy ją dekodując), a pyannote/torchcodec zwraca `None` i diaryzacja się nie uda — `transcribe` pomija taki plik z komunikatem, a `trim` (też bez zmiany granic) zapisuje go od nowa z poprawnym nagłówkiem. Pobieranie nagrań w `sync` używa `rclone --ignore-existing`, więc przycięte pliki nie są nadpisywane oryginałami z Drive.

**Kontrola jakości** (`quality.py`): `status` pokazuje `!` przy podejrzanych transkrypcjach, `check` podaje szczegóły (z długością nagrania z ffprobe), GUI — ikona ostrzeżenia nad transkrypcją. Progi dobrane na sesjach użytkownika: zwykle 82–107 słów/min i przerwy ≤ 3 min; pętla Whispera = ≥ 8 identycznych wypowiedzi (≥ 3 słowa) pod rząd (krótkie „nie, nie” powtarzają się naturalnie); kopia sesji = ta sama treść tekstu. `fix-loops` (GUI: „Usuń powtórzenia” w okienku uwag) zostawia z każdej pętli pierwszą wypowiedź; kopia .txt/.json trafia do `~/.cache/rpg-chronicler/transkrypcje-poprzednie/<sesja>/<czas>/` (lokalnie), `--undo` / „Przywróć” ją odtwarza (sesja tylko z .txt wraca do samego .txt).

**Uzupełnij brakujące** (`backfill`, menu GUI „Uzupełnij brakujące…” z planem do potwierdzenia): `backfill.plan` wylicza z plików brakujące/nieaktualne skróty i cytaty, PDF-y (nieaktualne albo zmieniane przez nowy skrót/cytaty), encyklopedie każdej kampanii z kronikami (brak albo starsza niż kronika, skrót lub stan kampanii) i **tylko istniejące** dzienniki postaci starsze niż kronika kampanii. Wykonanie w kolejności skróty → cytaty → PDF-y → encyklopedie → dzienniki; błąd jednego kroku nie przerywa reszty, chyba że AI jest niedostępne (`LLMError(retryable=False)`).

**Archiwizacja** (`archive`): pliki sesji (`<nazwa>.*` w folderach nagrań/transkrypcji, `<nazwa>_<rodzaj>.*` w kronikach) trafiają do podfolderu `archiwum/`, lokalnie i na Drive (`rclone move --files-from-raw`) — inaczej `sync` pobrałby je z powrotem. `list_sessions` nie widzi podfolderów.

Stan przetwarzania wynika **wyłącznie z istnienia plików** (`Session.has_*`) — nie ma bazy danych. Każdy krok pomija sesje już przetworzone (chyba że `--force`). `sync` pobiera też gotowe transkrypcje/podsumowania z Drive, żeby nie powtarzać pracy.

**Usuwanie** (`delete`, GUI: menu „⋯” w nagłówku sesji): zakresy `kronika` (pliki `<nazwa>_*` w kronikach: kronika, skrót, cytaty, PDF, zapowiedź, `_discord.json`, lista wydarzeń - transkrypcja/notatki zostają), `od-nowa` (do tego `<nazwa>.*` w transkrypcjach - zostaje tylko nagranie; odmowa bez nagrania) i `sesja` (do tego nagranie i `oryginaly/<nazwa>.*`; CLI pyta o wpisanie nazwy albo wymaga `--yes`, GUI - zaznaczenia „Rozumiem…”). Najpierw Drive (`storage/drive.delete_on_gdrive`: `rclone delete --files-from-raw` do **kosza Google Drive**), a gdy się nie uda - nic lokalnie (inaczej `sync` pobrałby pliki z powrotem; `--offline` świadomie tylko lokalnie). Lokalnie pliki idą do kosza aplikacji `~/.local/share/rpg-chronicler/kosz/<nazwa>__<czas>/` z `usuniete.json` (oryginalne ścieżki); `--undo` przywraca najnowsze usunięcie, wpisy starsze niż 30 dni czyści każde kolejne usuwanie. Pamięć podręczna sesji (wydarzenia, poprzednie wersje kroniki i transkrypcji, analiza ciszy) jest kasowana. Encyklopedii, dzienników ani stanu kampanii usuwanie nie zmienia - `deletion.campaign_warnings` podpowiada, co odświeżyć.

**Sesje bez nagrania** (`notes.py`, `add-session`, GUI: „+” nad listą sesji / Ctrl+N): `<nazwa>.notatki.md` w `TXT_DIR` (na Drive jak transkrypcje); `list_sessions` je widzi, `Session.has_notes`, `has_source` = transkrypcja albo notatki (`has_transcript` zostaje fałszywe - mówcy, statystyki, jakość, cytaty po prostu ich nie dotyczą). Nazwa `Kampania_RRMMDD` z kampanii i daty (`notes.session_name`, istniejąca sesja = odmowa). Kronika z promptu `prompts/summary_notes.md` (notatki to zwykle punkty MG: rozwiń w opowieść, **nie dopisuj zdarzeń**, długość wg ilości materiału), bez mówców i dwóch kroków; po niej skrót, słownik i stan kampanii, **bez cytatów** (też w `backfill`). Lista obecnych zastępuje mapowanie mówców (`after_chronicle.session_characters`, `diary.was_present`). Notatki są materiałem poprawki kroniki i wyszukiwarki (`KIND_NOTES`, razem z transkrypcjami). Kronika starsza od notatek = nieaktualna (`notes.chronicle_is_stale`, etap na liście i ostrzeżenie w GUI). PDF i stopka Discorda mają adnotację „spisana z notatek Mistrza Gry” (`notes.ANNOTATION`). W GUI zakładka „Transkrypcja” nazywa się wtedy „Notatki” (podgląd + „Edytuj notatki…”), a „Mówcy” jest ukryta.

## Kampanie

Klucz kampanii = prefiks nazwy sesji przed `_`. Plik `TXT_DIR/kampanie.toml` (format: `kampanie.przyklad.toml`) leży w folderze transkrypcji, więc synchronizuje się z Drive; zapisuje go `campaigns.save_campaigns` (atomowo, komentarze ręczne nie są zachowywane). `load_campaigns()` ma pamięć podręczną unieważnianą po zmianie pliku (GUI działa długo). Kampania jest używana w:
- transkrypcji: `Campaign.all_names()` jako `hotwords` Whispera (ustawienie `transkrypcja.podpowiedz_nazw`; Whisper sam przycina listę do ~220 tokenów),
- kronice: `context.campaign_context()` = `Campaign.prompt_info()` (opis, postacie graczy, słownik) + kronika poprzedniej sesji tej kampanii (`previous_session()` wg daty z nazwy: `RRMMDD` lub `DD_MM_RRRR`, `campaigns.session_date`),
- sugestii mówców: lista postaci graczy w prompcie; w GUI menu imion przy polach mówców.

Słownik budowany z AI: `glossary KAMPANIA` (wszystkie kroniki) i automatycznie po każdej nowej kronice (`ai.propozycje_slownika`). Propozycje nie trafiają od razu do pliku — czekają w cache (`glossary.load_proposals`/`pending_for`), aż użytkownik je zatwierdzi w zakładce „Kampanie”. Prompt prosi o nazwy w mianowniku i JSON; `parse_response` toleruje tekst wokół JSON-a. Synchronizacja `TXT_DIR`/`SUMMARY_DIR` używa `rclone --update`, żeby starsza wersja z Drive nie nadpisała lokalnych zmian (kampanie, mówcy) i odwrotnie.

**Opisy haseł** (`Campaign.descriptions`, `[Kampania.opisy]` w `kampanie.toml`, nazwa → krótki opis): każda postać gracza i nazwa ze słownika może mieć opis i zdjęcie (`campaigns.set_image`/`image_path`, folder `obrazy/` w `TXT_DIR` - `rclone copy` przenosi podfoldery, `list_sessions` ich nie widzi). Opisy nazw usuniętych ze słownika odpadają przy zapisie. Brakujące opisy uzupełnia `describe KAMPANIA` (GUI: „Uzupełnij z kronik”) i każda encyklopedia z AI - z **tej samej odpowiedzi AI co encyklopedia** (`encyclopedia.ai_entries`, cache), więc bez nowych kronik nic nie kosztuje; istniejących (np. poprawionych ręcznie) nie zmienia, a encyklopedia bierze opis z kampanii przed opisem AI. GUI (zakładka Kampanie): wiersz nazwy z podglądem opisu i miniaturą, dymek z pełnym opisem i zdjęciem (`gui/entry_page.attach_tooltip`), kliknięcie → `EntryPage` (opis zapisuje się przy wyjściu ze strony, zdjęcie od razu). Do promptów kronik opisy na razie nie trafiają.

**Obrazki od AI** (`images.py`, `image KAMPANIA NAZWA`, przycisk „Wygeneruj obrazek (AI)” na stronie hasła): LLM pisze prompt po angielsku (`prompts/image_prompt.md`) z opisu hasła i **stylu kampanii** (`Campaign.image_style`, TOML `styl_obrazow`; pusty → przy pierwszym obrazku propozycja LLM z `prompts/image_style.md`, zapisana w kampanii, edycja w zakładce Kampanie → Ogólne), a rysuje Cloudflare Workers AI (`@cf/black-forest-labs/flux-1-schnell`, 4 kroki, 1024×1024; darmowe 10 000 neuronów/dzień ≈ 200 obrazków; `CLOUDFLARE_ACCOUNT_ID`/`CLOUDFLARE_API_TOKEN` w `.env`, token tylko z „Workers AI Read+Edit”). **Wskazówki użytkownika** (GUI: okienko po „Wygeneruj obrazek”/„Spróbuj ponownie”, CLI `--wskazowki`): dodatkowy opis po polsku, który ten sam LLM tłumaczy w prompcie obrazka i stawia przed opisem z kroniki (pole `{user_hints}`); ostatnie wskazówki hasła są w `<nazwa>.wskazowki.txt` obok propozycji i wypełniają okienko przy kolejnej próbie. Wynik to **propozycja** w `~/.cache/rpg-chronicler/obrazki/<kampania>/<nazwa>__<czas>.jpg` (+ `.txt` z promptem) - GUI: „Zachowaj” (`keep_candidate` → `set_image`) / „Spróbuj ponownie” / „Odrzuć”; CLI `--zachowaj` od razu. Lekcje z prób (2026-11): FLUX nie ma promptu negatywnego - „no signature/watermark” i słowa o papierze/pergaminie **przywołują** zmyślone podpisy, więc prompt kończy się „full-bleed image filling the entire frame, unsigned”; rasy fantasy trzeba opisać cechami ciała (sam „halfling” daje elfie uszy); słowa o dzieciach (child-sized) + broń/krew odrzuca filtr NSFW Cloudflare (HTTP 400). Bez nazw artystów i wydawców w stylu.

**Przed sesją i pytania** (zakładka Kampanie → podzakładka „Przed sesją”: grupy „Przed sesją” i „Zapytaj kronikarza”):
- `recap` (`prep.write_recap`, `prompts/recap.md`): tekst do przeczytania na głos (1–2 min) z **ostatniej** kroniki kampanii + krótko otwarte wątki ze stanu kampanii (zatwierdzonego, a bez niego z propozycji); prefiks = sama ostatnia kronika (jak skrót - cache). Bez `--force` pisze tylko, gdy tekst jest nieaktualny (`prep.is_current`: nagłówek ≠ ostatnia sesja albo kronika nowsza). `--discord` wysyła osadzenie bez załącznika na webhook kampanii (GUI pyta o potwierdzenie).
- `ideas` (`prep.write_ideas`, `prompts/session_ideas.md`, GUI: wiersz „Pomysły na następną sesję”): `prep.IDEAS_COUNT` (5) pomysłów na wydarzenia z ostatniej kroniki i stanu kampanii - każdy z tytułem, 2–4 zdaniami i wątkiem/sesją, z którą się wiąże; zróżnicowane (walka, rozmowa, tajemnica, komplikacja, okazja), nowe zdarzenia wolno wymyślać, ale nie przeczyć faktom ani rozstrzygać za graczy. Prefiks jak „Poprzednio” (ostatnia kronika - cache). Zawsze pisze nowe; gdy plik jest po tej samej sesji, AI dostaje poprzednie pomysły z prośbą, żeby ich nie powtarzać.
- `gm-notes` (`prompts/gm_notes.md`): sekcje Otwarte wątki / Obietnice, długi i zobowiązania / Niewykorzystane tropy / BN-i do przypomnienia / Pytania bez odpowiedzi, każdy punkt z sesją w nawiasie; ze wszystkich kronik (prefiks jak encyklopedia, `prep.CHRONICLES_LIMIT`) i stanu kampanii; .md zapisuje `prep` (z nagłówkiem), komenda dorabia PDF.
- `ask` (`ask.py`, `prompts/ask.md`): odpowiedź tylko z kronik/stanu/słownika, fakty z `[Nazwa_sesji]`; `referenced_sessions` zostawia istniejące sesje kampanii (GUI: przyciski → kronika sesji, `CampaignsView.open_session`). Historia lokalnie `~/.cache/rpg-chronicler/pytania/<kampania>.json` (30 ostatnich, w GUI 5).

## Pamięć kampanii

`memory.py`: zwięzły stan świata po ostatniej sesji (sekcje: Drużyna, Zasoby i ekwipunek, Gdzie jesteśmy, Otwarte wątki, Ważni BN-i, Zamknięte wątki; prompt `prompts/campaign_state.md`). Po każdej nowej kronice (`ai.pamiec_kampanii`) AI aktualizuje stan — gdy stanu nie ma, buduje go ze wszystkich kronik kampanii. Wynik to **propozycja** w cache; kolejne kroniki przed zatwierdzeniem aktualizują tę propozycję. Zatwierdza użytkownik (GUI: zakładka „Kampanie”, z możliwością poprawek; CLI: `memory KAMPANIA --accept`). Do kroniki sesji trafia (`context.campaign_context`) tylko stan sprzed tej sesji (`memory.is_before`; stan bez nagłówka = wpisany ręcznie, zawsze), a stan aktualizuje się tylko kroniką sesji nowszej niż ta, po której go zapisano — ponowne pisanie starszej kroniki nie cofa stanu. Gdy propozycja sprzed sesji czeka na zatwierdzenie (`memory.unaccepted_warning`), `summarize` wypisuje ostrzeżenie, a GUI przed generowaniem kroniki pyta („Otwórz Kampanie” / „Generuj mimo to”) - kronika dostałaby tylko stan zatwierdzony.

## Kronika w dwóch krokach

Gdy `ai.kronika_etapami` (domyślnie włączone) i transkrypcja ma ponad ~1 h (`Transcript.split_parts`, części po `CHRONICLE_PART_SECONDS` = 45 min, cięcie przy zmianie mówcy, krótka końcówka dołącza do poprzedniej): z każdej części AI robi rzeczową listę wydarzeń z cytatami (`prompts/events.md`, z kontekstem: kampania, stan kampanii, wydarzenia poprzedniej części), a kronika (`prompts/summary.md`, pole `{source}`) powstaje z połączonych list zamiast z całej transkrypcji. Listy części są w `~/.cache/rpg-chronicler/wydarzenia/<sesja>/<sha1 promptu>.md` — przerwany przebieg ani `summarize --force` nie powtarzają zapytań, dopóki nie zmieni się transkrypcja, mówcy, kontekst ani prompt. Krótsze sesje idą jednym krokiem jak dawniej.

## Poprawka kroniki, wyszukiwarka, encyklopedia

- **Poprawka poleceniem** (`revise`, „Popraw…” w zakładce Kronika): `revision.revise_chronicle` daje AI kronikę, materiał źródłowy (lista wydarzeń `_wydarzenia.md`, a gdy jej nie ma - transkrypcja) i polecenie (`prompts/revise.md`: zmień tylko to, czego dotyczy polecenie). Poprzednia wersja trafia do `~/.cache/rpg-chronicler/kroniki-poprzednie/<sesja>/` (lokalnie, nie na Drive); `--undo` / „Cofnij poprawkę” przywraca najnowszą. Odpowiedź krótsza niż 30% kroniki jest odrzucana (`RevisionError`). Po poprawce odświeża się skrót (`ai.skrot_kroniki`); słownika i stanu kampanii poprawka nie rusza.
- **Wyszukiwarka** (`search`, okno Ctrl+F): `textmatch` porównuje początki słów (min. 4 litery) z wariantem bez ruchomego „e” (kupiec → kupca, Marek → Marka); nieregularnej odmiany (ojciec → ojca) nie łapie. Zapytanie z kilku słów musi trafić w okno do 3 kolejnych wypowiedzi, zaczynające się od wypowiedzi z którymś ze słów. Wyniki od najstarszej sesji (w sesji: kronika, potem transkrypcja wg czasu). GUI trzyma transkrypcje w `TranscriptCache` (odświeżane po zmianie pliku).
- **Encyklopedia** (`encyclopedia`, zakładka Kampanie): hasła = słownik kampanii + to, co AI znajdzie w kronikach (`prompts/encyclopedia.md`, JSON z opisem i listą sesji; jedno zapytanie na kampanię, odpowiedź w `~/.cache/rpg-chronicler/encyklopedia/`). Sesje hasła = dopasowanie pełnej nazwy w kronice (`textmatch.contains_name`) **lub** wskazanie AI (łapie „Fen” dla „Fen Wanderer” i nieregularną odmianę); sesje spoza kronik kampanii są odrzucane. Słownik decyduje o pisowni i kategorii. PDF: `chronicle_pdf.write_markdown_pdf` (ten sam styl co kroniki).

## Statystyki sesji i dziennik postaci

- **Statystyki** (`stats`, przycisk „Statystyki” nad transkrypcją): `stats.session_stats` liczy z segmentów i mapowania mówców (imiona ujednolicone `NameResolver`, gracz → postać) czas mówienia, wypowiedzi (ciągi segmentów jednego mówcy) i słowa; udział MG a graczy; przerwy = ≥ 3 min bez wypowiedzi (`BREAK_SECONDS`), czas gry = od pierwszej do ostatniej wypowiedzi bez przerw. Nagrania użytkownika są zwykle przycięte z ciszy, więc przerw zwykle nie ma. `--campaign K` dodaje sumę (`merge_stats`).
- **Dziennik postaci** (`diary KAMPANIA POSTAĆ`, zakładka Kampanie → „Dzienniki postaci”): wpis AI (`prompts/diary.md`, pierwsza osoba, tylko to, co postać przeżyła) o każdej sesji kampanii z kroniką, na której postać była - kronika wymienia ją lub skrót jej imienia (`diary.aliases`: „Fen Wanderer” → „Fen”, „Wanderer”; „Sir Amos” → „Amos”) albo mówiła wg mapowania mówców. Źródło: kronika + lista wydarzeń (prefiks wspólny dla dzienników różnych postaci), cytaty postaci i **poprzedni wpis** (bez niego wpisy pisane osobno zmieniały rodzaj gramatyczny postaci). Wpisy w `~/.cache/rpg-chronicler/dziennik/<kampania>/<sha1>.md` - odświeżenie po nowej sesji pyta tylko o nowy wpis; `--force` pisze wszystko od nowa. AI odpowiada „BRAK”, gdy postaci nie było - wpis jest pomijany. `canonical_character` zamienia „fen” na „Fen Wanderer” z kampanii.

## Rozpoznawanie graczy po głosie

Po transkrypcji (`transcribe_sessions`) liczą się odciski głosu każdego `SPEAKER_XX` (średnia ważona odcisków jego najdłuższych wypowiedzi, do 120 s mowy; ~10 s na sesję); dla starszych sesji `voices`. Profile głosów kampanii (`voices.campaign_profiles`) powstają na bieżąco z sesji tej kampanii, które mają `.mowcy.json` i `.glosy.json` — nie ma osobnego magazynu, więc poprawki imion od razu zmieniają profile. `NameResolver` ujednolica nazwy (wielkość liter, literówki ≥ 0.85 podobieństwa, gracz z `postacie_graczy` → jego postać). Kilka etykiet może dostać to samo imię (diaryzacja dzieli osoby).

Progi w `voices.py` dobrano testem „każda sesja na podstawie pozostałych” na nazwanych sesjach użytkownika (Warhammer + Fallout, 65 etykiet): „pewne” (najbliższy odcisk ≥ 0.65 i przewaga ≥ 0.10) ~96% trafnych przy ~40% etykiet; „możliwe” (miara łączona ≥ 0.5) ~78%. Zmieniając progi, powtórz taki test. GUI wpisuje pewne rozpoznania w pustej sesji, ale zapisuje je dopiero po zatwierdzeniu (bez autozapisu); terminalowe `speakers` przyjmuje pewną podpowiedź Enterem.

## Skrót kroniki

Po każdej nowej kronice (`ai.skrot_kroniki`, domyślnie włączone) AI pisze skrót z `prompts/brief.md`: **jeden akapit ciągłej opowieści** (6–10 zdań, ~1000 znaków), chronologicznie, z wydarzeniami łączonymi przyczyną i skutkiem, prostym językiem, kończący się tym, gdzie drużyna była na końcu sesji. Tak chce użytkownik — lista punktów („co się stało” w wyliczance) mu nie odpowiadała. Przykład stylu w prompcie jest celowo z wymyślonej kampanii, żeby AI nie przenosiło treści między kampaniami. Skrót jest nieaktualny, gdy kronika jest od niego nowsza (`chronicle.brief_is_current`); `brief` bez `--force` uzupełnia tylko brakujące/nieaktualne. W GUI przełącznik „Kronika / Skrót” w zakładce Kronika; w PDF ramka „W skrócie” na początku (PDF jest nieaktualny także, gdy skrót jest od niego nowszy).

## Cytaty z sesji

Po każdej nowej kronice (`ai.cytaty`, domyślnie włączone) AI wybiera wypowiedzi z gry (`prompts/quotes.md`, JSON z polem `czas`): co najmniej po jednej każdej postaci graczy obecnej na sesji (`after_chronicle.session_characters`: mapowanie mówców przez `NameResolver`, bez MG; bez mapowania - postacie z kampanii) plus 2–3 najciekawsze od kogokolwiek; najwyżej liczba postaci + 3 (bez postaci: 3–5). Źródło: sekcje „### Cytaty” z listy wydarzeń, jeśli mają czasy (`- [g:mm:ss] Postać: „…”`; kronika w dwóch krokach - tanio), a w przeciwnym razie transkrypcja z czasami (`Transcript.compact_for_llm(timestamps=True)`: wiersz `[g:mm:ss] MÓWCA: …`, długie wypowiedzi dzielone co 30 s). **Czas cytatu podaje AI, nie zgadujemy go dopasowaniem tekstu**; kod tylko zamienia go na fragment nagrania (`Transcript.line_span`: segment zaczynający się najbliżej, ≤ 2 s, plus kolejne segmenty tego mówcy do 30 s) i zapisuje `[początek–koniec]` (koniec w górę). Czas spoza transkrypcji jest pomijany - cytat zostaje bez odsłuchu. GUI: przycisk odsłuchu przy cytacie z czasem (`SnippetPlayer`, z zapasem 1 s przed i 4 s po - czasy Whispera bywają za wczesne, lepiej dłużej niż uciąć). Kronika jest na początku promptu (ten sam prefiks co skrót, słownik i stan kampanii - cache w API). Cytaty trafiają na koniec PDF (sekcja „Cytaty sesji”; PDF jest nieaktualny, gdy cytaty są od niego nowsze) i pod zapowiedź na Discordzie (`discord.description_with_quotes`, cytaty, które nie mieszczą się w limicie 4000 znaków, odpadają; `--no-quotes` / przełącznik w oknie wysyłki). W GUI trzecia pozycja przełącznika „Kronika / Skrót / Cytaty”; pasek nad kroniką ma tylko „Popraw…”, „PDF”, „Wyślij na Discord”, reszta w menu „⋯” (okno musi się mieścić w 1024 px - test dymny łapie `Adwaita-WARNING`). Dla starszych sesji: `quotes`.

## Udostępnianie kronik (PDF, Discord)

Wysyłka jest ręczna (przycisk w zakładce Kronika albo `discord SESJA`): wiadomość = osadzenie z tytułem kroniki (pierwsza linia), zapowiedzią i stopką „system · data sesji” + PDF w załączniku. Zapowiedź pisze AI (`prompts/teaser.md`) tylko, gdy nie ma pliku zapowiedzi — GUI pozwala ją poprawić przed wysłaniem. Ponowna wysyłka wymaga `--force` (GUI dodaje go sam po potwierdzeniu w oknie). **Stan wysyłki** (`chronicle.discord_state`): nie wysłano / wysłano / na Discordzie starsza wersja (kronika zmieniona po dacie wysyłki - poprawka, nowa kronika); widać go na liście sesji (samolot przy sesji, ostrzegawczy przy starszej wersji), nad kroniką i w kolumnie DISCORD `status`. Discord nie pozwala webhookowi przejrzeć kanału, więc kroniki wysłane, zanim aplikacja zapisywała wysyłki (albo ręcznie), oznacza się samemu: menu „⋯” w zakładce Kronika → „Oznacz jako wysłaną na Discord” / `discord SESJA --oznacz` (`--odznacz` usuwa znacznik, wiadomość zostaje). Webhooki per kampania są w **lokalnych** ustawieniach (`[discord] Kampania = "url"`, `settings.DYNAMIC_SECTIONS`), nie w `kampanie.toml`, bo adres pozwala pisać na kanał, a plik kampanii trafia na Drive. Discord wymaga własnego `User-Agent` (`DiscordBot (...)`), domyślny z urllib bywa blokowany.

PDF: emoji są usuwane (`chronicle_pdf.strip_emoji`) — systemowa czcionka Noto Color Emoji jest w formacie COLRv1, którego poppler (przeglądarka PDF w GNOME) nie wyświetla, a jednokolorowa Noto Emoji też miała puste glify. WeasyPrint dzieli wyrazy po polsku (`lang="pl"`, `hyphens: auto`).

## Przepływ podsumowania

`summarize_sessions` → dla sesji z transkrypcją bez podsumowania: wczytaj mapowanie mówców → jeśli brak i tryb interaktywny, zapytaj i wywołaj `identify_speakers`; jeśli nieinteraktywny i brak `--allow-unnamed`, pomiń → `chronicle_source()`: lista wydarzeń z części (kronika w dwóch krokach) albo `transcript.compact_for_llm(mapping)` (bez czasów, sklejone wypowiedzi — oszczędność tokenów) → `render("summary", ..., source=...)` → `with_retry(client.generate)` → zapis → `after_chronicle.run_all`: skrót, cytaty, propozycje słownika, propozycja stanu kampanii.

**Długość kroniki** (`prompts/summary.md`): zwięźle, ale wszystkie ważne wydarzenia; punkty tylko dla konkretów (łupy, pieniądze, ustalenia, transakcje, decyzje), nie dla każdej akcji graczy; zakaz pomijania imion, miejsc i przedmiotów zostaje (korzystają z nich słownik, encyklopedia, dziennik). **Nie dodawaj limitu słów ani liczby sekcji** - użytkownik miał je wcześniej i AI wycinało wtedy kawałki sesji. Typowa kronika ma 600–1000 słów (3–5 min czytania); za długie były te, w których AI wypunktowało każdą akcję (50–75 punktów).

Klient LLM tworzony leniwie (`llm.LazyClient`; w testach podmienia się `llm.get_client`), więc brak klucza API nie przeszkadza, gdy nic nie ma do zrobienia.

## Ustawienia

`config.py` przy imporcie wczytuje `settings.load()`; klucze z pliku (np. `transkrypcja.watki`, `foldery.nagrania`, `ai.dostawca`) nadpisują wartości domyślne. Plik zawiera tylko zmienione klucze; lista dozwolonych kluczy i typów to `settings.FIELDS` (błędne wpisy są pomijane z ostrzeżeniem). `ai.dostawca` ma pierwszeństwo przed `LLM_PROVIDER` z `.env`, a `--provider` przed oboma. Ścieżkę pliku zmienia `RPG_CHRONICLER_SETTINGS` — `tests/conftest.py` ustawia ją na nieistniejący plik, żeby testy nie zależały od ustawień użytkownika.

Nowe ustawienie edytowalne z GUI: klucz w `settings.FIELDS`, odczyt w `config.py` przez `_setting()`, pole w `gui/settings_dialog.py`. Procesy CLI czytają ustawienia przy starcie, więc działają od następnego zadania; wartości używane przez samo GUI (foldery) wymagają restartu (`win.restart` → `os.execv`).

## GUI

- **Dwa interpretery:** GUI działa na systemowym `/usr/bin/python3` (Fedora: PyGObject, GTK 4, libadwaita), bo PyGObject nie ma w `.venv`. Ciężką pracę (transkrypcja, LLM, rclone) zleca procesowi `.venv/bin/rpg-chronicler` z `--no-interactive` i `RPG_CHRONICLER_PROGRESS=json`.
- Dlatego `gui/` może importować tylko moduły bez zależności zewnętrznych: `config`, `settings`, `session`, `notes`, `transcript`, `campaigns`, `voices`, `chronicle`, `discord`, `audio_trim`, `progress`, `quality`, `stats`, cały `campaign_tools/` (`glossary`, `memory`, `encyclopedia`, `diary`, `prep`, `ask`, `images`) i `maintenance/` (`archive`, `deletion`, `backfill`) (`diary` liczy ścieżkę listy wydarzeń sam, bo `chronicle_events` importuje `llm`; `memory` importuje `llm` dopiero w funkcjach z klientem; `glossary` importuje `llm` dopiero wewnątrz `extract_proposals`). **Nie importuj w GUI** `summary`, `llm`, `transcription`, `storage`. Te moduły muszą działać na Pythonie 3.11 (`.venv`) i systemowym (obecnie 3.15).
- Interakcja z użytkownikiem w GUI zamiast `input()`: sugestia mówców przez `speakers --suggest-only` (zapis do `.mowcy-sugestia.md`), imiona zapisuje GUI bezpośrednio (`save_speaker_mapping`).
- Nowy długi etap w CLI → wołaj `progress.report(etap, sesja, zrobione, razem)`; bez zmiennej środowiskowej nic nie wypisuje. Wyjście `\r` (np. rclone -P) GUI pokazuje tylko w pasku stanu, nie w logu.
- Przy starcie GUI sprawdza w tle, czy `.venv` importuje faster-whisper/pyannote/torchcodec; jeśli nie, pokazuje `Adw.Banner` z instrukcją `./sprawdz-srodowisko --napraw`. Wynik `audio_trim.has_duration_header` (ffprobe) jest zapamiętywany per wersja pliku (ścieżka, rozmiar, data).
- **Układ okna:** główne okno ma dwie zakładki (`main_stack`, przełącznik `Adw.InlineViewSwitcher` nad listą): „Sesje” (lista sesji + zakładki Transkrypcja/Mówcy/Kronika) i „Kampanie” (`CampaignsView`: lista kampanii + strona kampanii). Strona kampanii ma podzakładki (`campaigns_view.TABS`); hasło słownika (`EntryPage`) wchodzi na nią jako kolejna strona `Adw.NavigationView`. Okno musi się mieścić w 1024 px: lista po lewej ma 280 px (szerszy rząd nad listą ścieśnia nagłówek kroniki), a piąta podzakładka kampanii już się nie mieściła. `show_campaigns(klucz)` przełącza na zakładkę Kampanie (z przycisku „Kampania X”, toastów z propozycjami AI, okna Discorda); przejście na „Sesje” odświeża listę sesji.
- Logikę, którą da się testować bez GTK, umieszczaj w `gui/text.py` (testy: `tests/test_gui_text.py`). **Test dymny GUI** (`tests/test_gui_smoke.py`, znacznik `gui`): uruchamia `gtk4-broadwayd` i systemowym Pythonem `tests/gui_smoke.py` na tymczasowych danych - buduje wszystkie widoki (zakładki, wyszukiwarka, zakładka Kampanie, Discord, Ustawienia, okno poprawki) i nie toleruje `Gtk-CRITICAL`/`Gtk-WARNING`; pomija się bez Broadway/GTK. Nowy widok lub okno → dopisz krok w `gui_smoke.py`. Ręcznie okno można sprawdzić bez ekranu: `gtk4-broadwayd :5 &` i `GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 PYTHONPATH=src /usr/bin/python3 -m rpg_chronicler.gui`.

## Zasady przy zmianach

- Nowe ustawienia → stała w `config.py`; sekrety tylko z `.env` (nigdy w kodzie, `.env` jest w `.gitignore`).
- Nowy dostawca LLM: klasa z atrybutem `name` i metodą `generate(prompt) -> str`, rzucająca `LLMError(retryable=...)`; dopisać w `llm/__init__.get_client` i w `cli/parser.PROVIDERS`. Import SDK wewnątrz modułu/konstruktora (zależności opcjonalne).
- Prompty edytuj w `prompts/*.md`; dosłowne `{`/`}` muszą być podwojone (`str.format`).
- **Cache promptów (API Anthropic):** zapytania wołaj przez `llm.generate(client, prompt, prefix)`. `prefix` to stały początek wspólny dla kilku zapytań z rzędu - w szablonie oddzielony linią `---8<---` (`prompts.render_split`) albo kroniki z `prompts.chronicle_blocks` (skrót, słownik i stan kampanii po nowej kronice zaczynają się od tego samego bloku). Klient z `caches_prefix = True` wysyła go jako osobny blok z `cache_control` (5 min), pozostali dostają sklejony tekst. Prefiks musi być **bajt w bajt** taki sam, inaczej cache nie zadziała (testy: `tests/test_prompt_cache.py`). Zmienną treść (numer części, czas, transkrypcja) trzymaj po znaczniku.
- Zapisy transkrypcji przez `_write_atomic` (plik `.part` + `os.replace`).
- Ciężkie biblioteki (torch, faster-whisper, pyannote) importuj tylko w `transcription/` i leniwie z komend w `cli/`, żeby `status`, testy itp. działały szybko i bez nich.
- Komunikaty dla użytkownika: `print` z prefiksami `[SUKCES]`, `[BŁĄD]`, `[OSTRZEŻENIE]`, `[INFO]`, `[POMINIĘTO]`, `[PORAŻKA]`. Błąd pojedynczej sesji nie przerywa całego przebiegu.
- **CI** (`.github/workflows/testy.yml`): GitHub Actions przy każdym pushu, Python 3.11 i najnowszy 3.x, bez modeli (`pip install pytest markdown weasyprint` + `pip install --no-deps -e .`). Test, który potrzebuje torcha/pyannote, oznacza błąd w leniwych importach - napraw import, a nie test.
- Testy: używaj fixture `workspace` (monkeypatch ścieżek w `session`, `FakeLLM` zamiast `llm.get_client`; ustawienia dodatków w `after_chronicle`, dwóch kroków w `chronicle_events`). Testy nie mogą wymagać modeli, sieci, `rclone` ani `claude`.
- Transkrypcja działa tylko na CPU (`device="cpu"`, `int8`); strojenie przez `WHISPER_CPU_THREADS`, `WHISPER_VAD`, `WHISPER_BATCH_SIZE` i komendę `benchmark`.
- **Modele Whispera** (`benchmark SESJA --whisper-models medium large-v3-turbo --offset 1800 --save-text DIR`, pomiar 2026-11 na `Warhammer_261105`, 6 wątków): `medium` 0,25× czasu nagrania; `large-v3-turbo` 0,12× (ok. 2,5× szybciej) przy podobnej liczbie słów i jakości tekstu, ale z dłuższymi segmentami (8 segmentów ≥ 25 s na 10 min wobec 0 w medium - gorzej dla przypisania mówców). `large-v3` 0,65× (ok. 2,6× wolniej od medium, ~1 h 20 min na 2 h nagrania): najwięcej tekstu (1356 słów wobec 1137) i najmniej przekręceń zwykłych słów („kawałki stodoły”, „do strzyżenia owieczek”), ale imię „Sir Amos” zapisał źle, a medium dobrze. Turbo **musi** działać z `condition_on_previous_text=False` (`transcription/compare.uses_previous_text`), inaczej zapętla się („Tak?” ×34 zamiast monologu MG); z VAD i warunkowaniem jest jeszcze gorzej (241 słów). Domyślnie zostaje `medium`.
- `ClaudeCodeClient` uruchamia `claude` z `cwd=tempfile.gettempdir()`, żeby ten plik CLAUDE.md nie trafiał do promptu kroniki.

## Zależności zewnętrzne

- `ffmpeg`/`ffprobe` (przycinanie ciszy).
- `rclone` z remote'em `gdrive:` (foldery: `Audio_sesje_rpg`, `Transkrypcje_rpg`, `Podsumowania_rpg`).
- Token HuggingFace z akceptacją licencji `pyannote/speaker-diarization-3.1`.
- Dla `claude-code`: zainstalowane i zalogowane CLI `claude`.
- Python ≥ 3.11 (`tomllib`).
