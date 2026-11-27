# Kronikarz sesji RPG (rpg-chronicler)

Program dla Mistrza Gry: z nagrania sesji RPG robi transkrypcję z podziałem na mówców, a z niej klimatyczną kronikę sesji, którą można wysłać graczom jako PDF albo na Discord.

Transkrypcja działa lokalnie na procesorze (bez karty graficznej): [faster-whisper](https://github.com/SYSTRAN/faster-whisper) rozpoznaje mowę, a [pyannote](https://github.com/pyannote/pyannote-audio) rozpoznaje mówców. Kroniki i dodatki pisze model językowy (Claude albo Gemini).

## Co potrafi

- **Nagrania z Google Drive** (przez `rclone`): pobiera nowe nagrania, a gotowe transkrypcje i kroniki wysyła z powrotem.
- **Nagrywanie sesji** z mikrofonu w programie, z wskaźnikiem głośności, automatycznym filtrem i odpornością na awarie.
- **Transkrypcja po polsku** z rozpoznawaniem mówców, przycinaniem ciszy i kontrolą jakości (np. zapętlenia Whispera).
- **Rozpoznawanie graczy po głosie** na podstawie wcześniejszych sesji kampanii.
- **Kronika sesji** pisana przez AI, a do tego skrót, cytaty z odsłuchem fragmentu nagrania, PDF i wysyłka na Discord.
- **Kampanie:** słownik nazw (postacie, miejsca, przedmioty) z opisami i obrazkami, pamięć kampanii (stan świata po ostatniej sesji), encyklopedia, dzienniki postaci.
- **Przed sesją:** „Poprzednio w kampanii…” do przeczytania na głos, pomysły na następną sesję i notatki MG.
- **„Zapytaj kronikarza”:** pytania o przebieg kampanii z odpowiedzią na podstawie kronik.
- **Sesje bez nagrania:** kronika z notatek MG.
- **Wyszukiwarka** po kronikach i transkrypcjach.
- Okno programu (Linux i Windows) i pełny interfejs wiersza poleceń.

Interfejs, komunikaty i prompty są po polsku. Kroniki również powstają po polsku.

## Wymagania

Program powstał i jest używany na **Linuksie (Fedora)**. Na innych dystrybucjach powinien działać po doinstalowaniu odpowiedników pakietów. Na Windowsie działa z instalatorem (wersja testowa) - patrz „Instalacja na Windowsie”. Na macOS nie był sprawdzany.

- Python 3.11 do części obliczeniowej (dla nowszych wersji może brakować `onnxruntime`).
- Do okna programu: systemowy Python z PyGObject i WebKitGTK 6 (Fedora: `python3-gobject`, `webkitgtk6.0`). Bez nich okno otworzy się w przeglądarce.
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
./rpg-chronicler-okno           # menu ☰ → Ustawienia → Klucze API: wklej token Hugging Face (i klucz AI, jeśli potrzebny)
./sprawdz-srodowisko            # sprawdza, czy wszystko jest na miejscu
```

`sprawdz-srodowisko --napraw` instaluje torch, torchaudio i torchcodec w wersjach **CPU**. Zwykły `pip install` ściąga wersje z CUDA (kilka GB więcej), a pyannote nie odczyta wtedy plików bez bibliotek CUDA.

Przy pierwszej transkrypcji modele Whisper i pyannote pobierają się same (ok. 2 GB).

## Instalacja na Windowsie (wersja testowa)

Na Windowsie okno programu korzysta z wbudowanego w system Edge WebView2. Są też komendy w konsoli.

1. Pobierz program: na GitHubie **Code → Download ZIP**, a potem rozpakuj go, np. do `Dokumenty\rpg-chronicler`.
2. Kliknij dwa razy **`instaluj-windows.bat`**. Windows może ostrzec, że plik pochodzi z internetu: kliknij „Więcej informacji” → „Uruchom mimo to”.
3. Instalator sam przygotuje wszystko, co potrzebne: Python 3.11, biblioteki Visual C++ (zapyta o zgodę administratora), ffmpeg, PyTorch w wersji na procesor i biblioteki programu. Na koniec zapyta o token Hugging Face i o to, które AI ma pisać kroniki. Zajmuje to zwykle 10–20 minut. Jeśli coś się nie uda, uruchom go ponownie: pominie to, co już jest.
4. Otwórz skrót **„RPG Chronicles”** z pulpitu albo menu Start. Nagrania wrzucaj do `Dokumenty\Audio_sesje_rpg`. Skrót **„RPG Chronicles (konsola)”** otwiera konsolę z gotowymi komendami (np. `rpg-chronicler run --offline`).

Pobieranie z Google Drive (rclone) i Claude Code trzeba na Windowsie zainstalować osobnie.

## Konfiguracja

- **Klucze API:** najprościej w oknie programu: menu ☰ → Ustawienia → „Klucze API”. Przy każdej usłudze są linki do stron, na których zakłada się klucz, i krótka instrukcja. Klucze zapisują się w pliku `.env` w folderze programu (prawa tylko dla Ciebie). Można go też edytować ręcznie (`cp .env.example .env`): `HUGGINGFACE_TOKEN`, `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`, `LLM_PROVIDER` i `CLOUDFLARE_*`. Plik jest w `.gitignore`, nie wrzucaj go nigdzie.
- **Ustawienia:** w oknie programu (menu ☰ → Ustawienia) albo `~/.config/rpg-chronicler/ustawienia.toml`. Ustawia się tam między innymi:
  - foldery: domyślnie `~/Documents/Audio_sesje_rpg`, `~/Documents/Transkrypcje`, `~/Documents/Podsumowania`,
  - foldery na Google Drive,
  - dostawcę AI,
  - liczbę wątków transkrypcji,
  - adresy webhooków Discorda dla kampanii.
- **Kampanie:** plik `kampanie.toml` w folderze transkrypcji, najwygodniej edytowany w oknie programu (zakładka „Kampanie”). Format pokazuje `kampanie.przyklad.toml`.

Nazwa pliku nagrania wyznacza sesję i kampanię: `Kampania_RRMMDD.m4a` (np. `Zakon_261015.m4a`). Część przed pierwszym `_` to kampania, a data służy do ustalenia kolejności sesji.

## Uruchamianie

```bash
./rpg-chronicler-okno                # okno programu (--przegladarka: w przeglądarce)
./rpg-chronicler-okno --instaluj     # wpis w menu aplikacji (--pulpit: także skrót na pulpicie)

.venv/bin/rpg-chronicler             # cały przebieg: pobranie → transkrypcja → kroniki → wysyłka na Drive
.venv/bin/rpg-chronicler status      # stan wszystkich sesji
.venv/bin/rpg-chronicler --help      # lista komend
```

Transkrypcja 2-godzinnego nagrania trwa ok. 1 godz. 20 min (procesor Ryzen 5 7500F, model `medium`, 6 wątków); większość tego czasu zajmuje rozpoznawanie mówców. Na słabszym procesorze będzie dłużej. Szybkość na swoim komputerze sprawdzisz komendą `benchmark`. Bardzo długie nagrania potrzebują dużo pamięci: 4-godzinna sesja z `pyannote` zajęła w szczycie ok. 17 GB RAM.

Rozpoznawanie mówców ma dwa silniki (ustawienia → „Rozpoznawanie głosów”): `pyannote` (domyślny) i nowy `onnx`, ok. 6 razy szybszy, ale z nieco innym podziałem na mówców. Gdy dwóch graczy o podobnych głosach trafia do jednego mówcy, obniż próg rozdzielania głosów tej kampanii (zakładka Kampanie → Ogólne, np. 0,65).

Dane kampanii (słownik, opisy, zdjęcia, przygotowania) synchronizują się przez Google Drive w obie strony: zmiany z drugiego komputera trafiają tutaj i odwrotnie, a gdy ten sam plik zmieni się na obu, program pokaże obie wersje i zapyta, którą zostawić.

Sesję można nagrać w programie: „+” nad listą sesji → „Nagraj sesję…”. Po zatrzymaniu nagranie przechodzi przez filtr (ustawienia → „Nagrywanie sesji”) i trafia jako FLAC do folderu nagrań. W konsoli: `rpg-chronicler record Kampania_RRMMDD`.

Prompty AI (kronika, skrót, cytaty, encyklopedia…) można podejrzeć i zmienić w oknie programu: menu ☰ → „Prompty AI”. Zmienione zapisują się na tym komputerze, a „Przywróć domyślny” cofa zmianę.

Testy: `.venv/bin/python -m pytest`. Testy nie potrzebują modeli ani sieci.

## Licencja

[PolyForm Noncommercial 1.0.0](LICENSE). Możesz za darmo pobierać, używać, zmieniać i udostępniać ten program, także w zmienionej wersji, ale **tylko w celach niekomercyjnych**: do grania, nauki, zabawy, projektów hobbystycznych. Sprzedaż programu albo jego przeróbek i płatne usługi na nim oparte są niedozwolone bez zgody autora. Każda kopia musi zawierać plik `LICENSE` razem z linią „Required Notice”.

Program jest dostarczany „tak jak jest”, bez żadnej gwarancji.

Biblioteki i modele, których program używa (faster-whisper, pyannote, PyTorch, WeasyPrint i inne), mają własne licencje. Pobierasz je osobno i obowiązują ich warunki. Silnik `onnx` pobiera modele [pyannote segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) (MIT, © CNRS; wersja ONNX: [k2-fsa](https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0)) i [WeSpeaker ResNet34-LM](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM) (CC BY 4.0).

## Zastrzeżenie

To prywatny projekt fana gier fabularnych. Nie jest związany z wydawcami ani właścicielami marek gier RPG wymienionych w przykładach i testach (np. Warhammer, Fallout, Dragonbane) ani przez nich wspierany. Nazwy te służą tylko do opisania, z jakimi kampaniami program był używany.
