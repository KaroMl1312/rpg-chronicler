# Kronikarz sesji RPG (rpg-chronicler)

Program dla Mistrza Gry: z nagrania sesji RPG robi transkrypcję z podziałem na mówców, a z niej klimatyczną kronikę sesji, którą można wysłać graczom jako PDF albo na Discord.

Transkrypcja działa lokalnie na procesorze (bez karty graficznej): [faster-whisper](https://github.com/SYSTRAN/faster-whisper) rozpoznaje mowę, a [pyannote](https://github.com/pyannote/pyannote-audio) rozpoznaje mówców. Kroniki i dodatki pisze model językowy (Claude albo Gemini).

## Co potrafi

- **Nagrania z Google Drive** (przez `rclone`): pobiera nowe nagrania, a gotowe transkrypcje i kroniki wysyła z powrotem.
- **Transkrypcja po polsku** z rozpoznawaniem mówców, przycinaniem ciszy i kontrolą jakości (np. zapętlenia Whispera).
- **Rozpoznawanie graczy po głosie** na podstawie wcześniejszych sesji kampanii.
- **Kronika sesji** pisana przez AI, a do tego skrót, cytaty z odsłuchem fragmentu nagrania, PDF i wysyłka na Discord.
- **Kampanie:** słownik nazw (postacie, miejsca, przedmioty) z opisami i obrazkami, pamięć kampanii (stan świata po ostatniej sesji), encyklopedia, dzienniki postaci.
- **Przed sesją:** „Poprzednio w kampanii…” do przeczytania na głos, pomysły na następną sesję i notatki MG.
- **„Zapytaj kronikarza”:** pytania o przebieg kampanii z odpowiedzią na podstawie kronik.
- **Sesje bez nagrania:** kronika z notatek MG.
- **Wyszukiwarka** po kronikach i transkrypcjach.
- GUI (GTK 4 + libadwaita) i pełny interfejs wiersza poleceń.

Interfejs, komunikaty i prompty są po polsku. Kroniki również powstają po polsku.

## Wymagania

Program powstał i jest używany na **Linuksie (Fedora)**. Na innych dystrybucjach powinien działać po doinstalowaniu odpowiedników pakietów. Na Windowsie działa wersja bez okna (konsola), z instalatorem - patrz „Instalacja na Windowsie”. Na macOS nie był sprawdzany.

- Python 3.11 do części obliczeniowej (dla nowszych wersji może brakować `onnxruntime`).
- Systemowy Python z PyGObject, GTK 4 i libadwaita do GUI (Fedora: `python3-gobject`, `gtk4`, `libadwaita`).
- `ffmpeg` / `ffprobe`.
- `rclone` z remote'em `gdrive:`, jeśli nagrania mają przychodzić z Google Drive (opcjonalnie; można też wrzucać pliki do folderu lokalnie).
- Darmowy token [HuggingFace](https://huggingface.co/settings/tokens) z zaakceptowaną licencją modelu [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1).
- Dostęp do modelu językowego, jedno z:
  - zalogowane [Claude Code](https://claude.com/claude-code) (`claude`) z planem Pro/Max (domyślnie),
  - klucz API Anthropic,
  - klucz API Gemini.
- Opcjonalnie konto Cloudflare do obrazków od AI (darmowy dzienny limit Workers AI).

## Instalacja

```bash
git clone https://github.com/KaroMl1312/rpg-chronicler.git
cd rpg-chronicler
./sprawdz-srodowisko --napraw   # tworzy .venv (Python 3.11, torch w wersji CPU) i instaluje program
./rpg-chronicler-gui            # Ustawienia → Klucze API: wklej token Hugging Face (i klucz AI, jeśli potrzebny)
./sprawdz-srodowisko            # sprawdza, czy wszystko jest na miejscu
```

`sprawdz-srodowisko --napraw` instaluje torch, torchaudio i torchcodec w wersjach **CPU**. Zwykły `pip install` ściąga wersje z CUDA (kilka GB więcej), a pyannote nie odczyta wtedy plików bez bibliotek CUDA.

Przy pierwszej transkrypcji modele Whisper i pyannote pobierają się same (ok. 2 GB).

## Instalacja na Windowsie (wersja testowa)

Na Windowsie program działa na razie **bez okna**, z komend w konsoli.

1. Pobierz program: na GitHubie **Code → Download ZIP**, a potem rozpakuj go, np. do `Dokumenty\rpg-chronicler`.
2. Kliknij dwa razy **`instaluj-windows.bat`**. Windows może ostrzec, że plik pochodzi z internetu: kliknij „Więcej informacji” → „Uruchom mimo to”.
3. Instalator sam przygotuje wszystko, co potrzebne: Python 3.11, biblioteki Visual C++ (zapyta o zgodę administratora), ffmpeg, PyTorch w wersji na procesor i biblioteki programu. Na koniec zapyta o token Hugging Face i o to, które AI ma pisać kroniki. Zajmuje to zwykle 10–20 minut. Jeśli coś się nie uda, uruchom go ponownie: pominie to, co już jest.
4. Otwórz skrót **„RPG Chronicles”** z pulpitu albo menu Start. To konsola z gotowymi komendami. Nagrania wrzucaj do `Dokumenty\Audio_sesje_rpg`, a potem wpisz `rpg-chronicler run --offline`.

Pobieranie z Google Drive (rclone) i Claude Code trzeba na Windowsie zainstalować osobnie.

## Konfiguracja

- **Klucze API:** najprościej w GUI, w oknie ustawień na stronie „Klucze API”. Przy każdej usłudze są linki do stron, na których zakłada się klucz, i krótka instrukcja. Klucze zapisują się w pliku `.env` w folderze programu (prawa tylko dla Ciebie). Można go też edytować ręcznie (`cp .env.example .env`): `HUGGINGFACE_TOKEN`, `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`, `LLM_PROVIDER` i `CLOUDFLARE_*`. Plik jest w `.gitignore`, nie wrzucaj go nigdzie.
- **Ustawienia:** okno ustawień w GUI albo `~/.config/rpg-chronicler/ustawienia.toml`. Ustawia się tam między innymi:
  - foldery: domyślnie `~/Documents/Audio_sesje_rpg`, `~/Documents/Transkrypcje`, `~/Documents/Podsumowania`,
  - foldery na Google Drive,
  - dostawcę AI,
  - liczbę wątków transkrypcji,
  - adresy webhooków Discorda dla kampanii.
- **Kampanie:** plik `kampanie.toml` w folderze transkrypcji, najwygodniej edytowany w GUI (zakładka „Kampanie”). Format pokazuje `kampanie.przyklad.toml`.

Nazwa pliku nagrania wyznacza sesję i kampanię: `Kampania_RRMMDD.m4a` (np. `Zakon_261015.m4a`). Część przed pierwszym `_` to kampania, a data służy do ustalenia kolejności sesji.

## Uruchamianie

```bash
./rpg-chronicler-gui                 # GUI
./rpg-chronicler-gui --instaluj      # wpis w menu aplikacji (--pulpit: także skrót na pulpicie)

.venv/bin/rpg-chronicler             # cały przebieg: pobranie → transkrypcja → kroniki → wysyłka na Drive
.venv/bin/rpg-chronicler status      # stan wszystkich sesji
.venv/bin/rpg-chronicler --help      # lista komend
```

Transkrypcja 2-godzinnego nagrania na procesorze trwa mniej więcej 30–40 minut (model `medium`, 6 wątków). Szybkość na swoim komputerze sprawdzisz komendą `benchmark`.

Testy: `.venv/bin/python -m pytest`. Testy nie potrzebują modeli ani sieci.

## Licencja

[PolyForm Noncommercial 1.0.0](LICENSE). Możesz za darmo pobierać, używać, zmieniać i udostępniać ten program, także w zmienionej wersji, ale **tylko w celach niekomercyjnych**: do grania, nauki, zabawy, projektów hobbystycznych. Sprzedaż programu albo jego przeróbek i płatne usługi na nim oparte są niedozwolone bez zgody autora. Każda kopia musi zawierać plik `LICENSE` razem z linią „Required Notice”.

Program jest dostarczany „tak jak jest”, bez żadnej gwarancji.

Biblioteki i modele, których program używa (faster-whisper, pyannote, PyTorch, WeasyPrint i inne), mają własne licencje. Pobierasz je osobno i obowiązują ich warunki.

## Zastrzeżenie

To prywatny projekt fana gier fabularnych. Nie jest związany z wydawcami ani właścicielami marek gier RPG wymienionych w przykładach i testach (np. Warhammer, Fallout, Dragonbane) ani przez nich wspierany. Nazwy te służą tylko do opisania, z jakimi kampaniami program był używany.
