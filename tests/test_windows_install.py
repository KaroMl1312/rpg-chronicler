"""Instalator na Windowsa: format plików (nie da się go uruchomić na Linuksie) i ffmpeg z folderu programu."""
import os
import re
from pathlib import Path

from rpg_chronicler import config

ROOT = Path(__file__).resolve().parents[1]
BATCH_FILES = [ROOT / "instaluj-windows.bat", ROOT / "windows" / "konsola.bat"]
PS1 = ROOT / "windows" / "instaluj.ps1"


def test_batch_files_are_ascii_with_crlf():
    # cmd.exe czyta .bat w stronie kodowej konsoli, a samo LF psuje skoki i etykiety
    for path in BATCH_FILES:
        data = path.read_bytes()
        assert data.isascii(), path.name
        assert b"\n" not in data.replace(b"\r\n", b""), path.name


def test_powershell_script_has_bom_and_crlf():
    # Windows PowerShell 5.1 bez BOM czyta plik jako ANSI - polskie litery i „cudzysłowy” by się rozsypały
    data = PS1.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_installer_references_existing_files():
    text = PS1.read_text(encoding="utf-8-sig")
    assert r"windows\konsola.bat" in text
    assert (ROOT / "windows" / "pomoc.txt").exists()
    assert "windows\\instaluj.ps1" in (ROOT / "instaluj-windows.bat").read_text(encoding="ascii")
    # torch w wersji CPU przed resztą, jak w ./sprawdz-srodowisko --napraw
    assert text.index("Instalacja PyTorch") < text.index("Instalacja programu")
    for key in re.findall(r'\$keys\["(\w+)"\]', text):
        assert key in {"HUGGINGFACE_TOKEN", "LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"}, key


def test_bundled_ffmpeg_goes_first_in_path(tmp_path, monkeypatch):
    bundled = tmp_path / "ffmpeg" / "bin"
    monkeypatch.setenv("PATH", "C:\\inne")
    config.use_bundled_ffmpeg(tmp_path)  # bez ffmpeg.exe - nic nie zmienia
    assert os.environ["PATH"] == "C:\\inne"

    bundled.mkdir(parents=True)
    (bundled / "ffmpeg.exe").write_bytes(b"")
    config.use_bundled_ffmpeg(tmp_path)
    config.use_bundled_ffmpeg(tmp_path)  # drugi raz nie dopisuje
    assert os.environ["PATH"] == str(bundled) + os.pathsep + "C:\\inne"
