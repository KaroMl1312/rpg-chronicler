# CLAUDE.md — rpg-chronicler

Opis projektu dla modelu AI pracującego w tym repozytorium. Kod, komentarze, komunikaty CLI i commity są **po polsku** — trzymaj się tego.

## Cel aplikacji

`rpg-chronicler` to CLI, które:
1. pobiera nagrania sesji RPG z Google Drive (przez `rclone`),
2. transkrybuje je lokalnie na CPU (faster-whisper, model `medium`, język `pl`) z rozpoznawaniem mówców (pyannote),
3. pozwala przypisać etykietom `SPEAKER_XX` imiona/role (z podpowiedzią LLM),
4. generuje klimatyczne „kroniki sesji” przez LLM (Claude Code / API Anthropic / Gemini),
5. wysyła transkrypcje i podsumowania z powrotem na Google Drive.

## Uruchamianie i testy

Projekt ma własne środowisko `.venv` na **Pythonie 3.11** (systemowy `python` to 3.15, a dla niego nie ma `onnxruntime`, którego wymaga faster-whisper). Zawsze używaj `.venv/bin/...`:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,anthropic,gemini]"   # (od)tworzenie środowiska
.venv/bin/rpg-chronicler                 # = rpg-chronicler run (sync → transkrypcja → podsumowania → upload)
.venv/bin/python -m rpg_chronicler status
.venv/bin/python -m pytest               # testy (szybkie, bez modeli i sieci)
```

Komendy (`src/rpg_chronicler/cli.py`): `run [--offline]`, `status`, `sync`, `transcribe`, `speakers`, `summarize [--force] [--allow-unnamed]`, `benchmark SESJA`, `migrate [--dry-run]`, `upload`. Większość przyjmuje opcjonalną listę nazw sesji; `--provider` wybiera LLM; `--interactive/--no-interactive` (domyślnie: czy stdin to TTY — dla crona tryb nieinteraktywny).

## Struktura

```
kampanie.toml                 # konfiguracja kampanii: [Prefiks] system=..., kontekst=...
.env / .env.example           # sekrety: HUGGINGFACE_TOKEN, GEMINI_API_KEY, ANTHROPIC_API_KEY, LLM_PROVIDER
src/rpg_chronicler/
  config.py                   # WSZYSTKIE stałe: ścieżki, remote'y rclone, modele, wątki, retry; własny loader .env
  cli.py                      # argparse, podkomendy cmd_*; ciężkie importy leniwie wewnątrz cmd_*
  session.py                  # Session (nazwa + ścieżki pochodne), list_sessions(), SessionNotFound
  campaigns.py                # Campaign, campaign_for(nazwa_sesji) na podstawie kampanie.toml
  transcript.py               # Segment, Transcript (JSON ⇄ .txt), compact_for_llm(), mapowanie mówców
  speakers.py                 # identify_speakers(): sugestia LLM + input() użytkownika
  summary.py                  # name_speakers(), summarize_sessions(), _LazyClient
  prompts/                    # szablony .md + render(name, **pola) (str.format → klamry trzeba podwajać)
  llm/                        # LLMClient (Protocol), LLMError(retryable), with_retry, get_client(provider)
    claude_code.py            #   `claude -p` w podprocesie (plan Pro/Max), bez narzędzi i MCP, cwd=tempdir
    anthropic_api.py          #   SDK anthropic, streaming, effort, server-side fallback (beta)
    gemini.py                 #   google-genai, wymuszony odstęp między zapytaniami
  transcription/
    runner.py                 # load_whisper/load_diarization/diarize/transcribe_audio, transcribe_sessions()
    merge.py                  # assign_speakers(): segment → mówca o największym pokryciu (wskaźnik przesuwny)
    benchmark.py              # pomiar szybkości na fragmencie nagrania
  storage/drive.py            # rclone copy w obie strony
tests/                        # pytest; conftest.py: fixture `workspace` (tmp katalogi + FakeLLM)
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
| `<nazwa>_podsumowanie.txt` | `SUMMARY_DIR` | kronika wygenerowana przez LLM |

Format linii .txt: `[SPEAKER_00] [12.34s -> 15.67s] tekst` lub (stare, bez mówców) `[12.34s -> 15.67s] tekst`. `load_transcript` preferuje JSON, a w razie braku parsuje .txt. Komenda `migrate` tworzy JSON z .txt, nie ruszając .txt.

Stan przetwarzania wynika **wyłącznie z istnienia plików** (`Session.has_*`) — nie ma bazy danych. Każdy krok pomija sesje już przetworzone (chyba że `--force`). `sync` pobiera też gotowe transkrypcje/podsumowania z Drive, żeby nie powtarzać pracy.

## Przepływ podsumowania

`summarize_sessions` → dla sesji z transkrypcją bez podsumowania: wczytaj mapowanie mówców → jeśli brak i tryb interaktywny, zapytaj i wywołaj `identify_speakers`; jeśli nieinteraktywny i brak `--allow-unnamed`, pomiń → `render("summary", ...)` z `transcript.compact_for_llm(mapping)` (bez czasów, sklejone wypowiedzi — oszczędność tokenów) → `with_retry(client.generate)` → zapis.

Klient LLM tworzony leniwie (`_LazyClient`), więc brak klucza API nie przeszkadza, gdy nic nie ma do zrobienia.

## Zasady przy zmianach

- Nowe ustawienia → stała w `config.py`; sekrety tylko z `.env` (nigdy w kodzie, `.env` jest w `.gitignore`).
- Nowy dostawca LLM: klasa z atrybutem `name` i metodą `generate(prompt) -> str`, rzucająca `LLMError(retryable=...)`; dopisać w `llm/__init__.get_client` i w `cli.PROVIDERS`. Import SDK wewnątrz modułu/konstruktora (zależności opcjonalne).
- Prompty edytuj w `prompts/*.md`; dosłowne `{`/`}` muszą być podwojone (`str.format`).
- Zapisy transkrypcji przez `_write_atomic` (plik `.part` + `os.replace`).
- Ciężkie biblioteki (torch, faster-whisper, pyannote) importuj tylko w `transcription/` i leniwie z `cli.py`, żeby `status`, testy itp. działały szybko i bez nich.
- Komunikaty dla użytkownika: `print` z prefiksami `[SUKCES]`, `[BŁĄD]`, `[OSTRZEŻENIE]`, `[INFO]`, `[POMINIĘTO]`, `[PORAŻKA]`. Błąd pojedynczej sesji nie przerywa całego przebiegu.
- Testy: używaj fixture `workspace` (monkeypatch ścieżek w `session`/`summary`, `FakeLLM` zamiast `get_client`). Testy nie mogą wymagać modeli, sieci, `rclone` ani `claude`.
- Transkrypcja działa tylko na CPU (`device="cpu"`, `int8`); strojenie przez `WHISPER_CPU_THREADS`, `WHISPER_VAD`, `WHISPER_BATCH_SIZE` i komendę `benchmark`.
- `ClaudeCodeClient` uruchamia `claude` z `cwd=tempfile.gettempdir()`, żeby ten plik CLAUDE.md nie trafiał do promptu kroniki.

## Zależności zewnętrzne

- `rclone` z remote'em `gdrive:` (foldery: `Audio_sesje_rpg`, `Transkrypcje_rpg`, `Podsumowania_rpg`).
- Token HuggingFace z akceptacją licencji `pyannote/speaker-diarization-3.1`.
- Dla `claude-code`: zainstalowane i zalogowane CLI `claude`.
- Python ≥ 3.11 (`tomllib`).
