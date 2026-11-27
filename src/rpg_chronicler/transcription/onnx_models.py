"""Pliki modeli rozpoznawania głosów bez PyTorcha: pobieranie (bez tokenu) i przygotowanie; tylko stdlib + numpy.

Segmentacja: pyannote segmentation-3.0 (licencja MIT, CNRS; wersja ONNX: k2-fsa/sherpa-onnx).
Głosy: WeSpeaker ResNet34-LM (licencja CC BY 4.0, https://github.com/wenet-e2e/wespeaker).
To te same sieci, których używa pyannote/speaker-diarization-3.1.
"""
import hashlib
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Wyjście ResNet-u przed uśrednianiem (cechy ramek): własne uśrednianie z maską mówcy zamiast wbudowanego
FRAMES_OUTPUT = "343"


class ModelDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    sha256: str


SEGMENTATION = ModelFile(
    "segmentacja.onnx",
    "https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/"
    "9403a6902bb58e3d5ae8c7e77c3422de279db2e0/model.onnx",
    "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079")
EMBEDDING = ModelFile(
    "glosy.onnx",
    "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/"
    "f0c48c298fd835726c27956a5d617bad7115627e/voxceleb_resnet34_LM.onnx",
    "7bb2f06e9df17cdf1ef14ee8a15ab08ed28e8d0ef5054ee135741560df2ec068")


def models_dir() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache) / "rpg-chronicler" / "modele"


def ensure_model(model: ModelFile) -> bytes:
    """Treść pliku modelu; pobiera go przy pierwszym użyciu i sprawdza sumę kontrolną."""
    path = models_dir() / model.name
    if path.exists():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == model.sha256:
            return data
    print(f"[INFO] Pobieranie modelu {model.name} (tylko za pierwszym razem)...")
    request = urllib.request.Request(model.url, headers={"User-Agent": "rpg-chronicler"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, OSError) as e:
        raise ModelDownloadError(f"Nie udało się pobrać modelu {model.name}: {e}") from e
    if hashlib.sha256(data).hexdigest() != model.sha256:
        raise ModelDownloadError(f"Pobrany model {model.name} jest uszkodzony (zła suma kontrolna).")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)
    return data


# --- przygotowanie modelu głosów ---
# Plik ONNX to protobuf. Zamiast dodatkowej biblioteki `onnx` wystarczą dwie proste operacje na bajtach:
# dopisanie wyjścia sieci i odczytanie wag ostatniej warstwy.

def _varint(data, position: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, position
        shift += 7


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _fields(data):
    """Pola komunikatu protobuf: (numer, wartość) - liczba albo fragment `data`."""
    position = 0
    while position < len(data):
        key, position = _varint(data, position)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, position = _varint(data, position)
        else:
            if wire == 2:
                size, position = _varint(data, position)
            else:
                size = {1: 8, 5: 4}[wire]
            value = data[position:position + size]
            position += size
        yield number, value


def _message(number: int, payload: bytes) -> bytes:
    return _encode_varint(number << 3 | 2) + _encode_varint(len(payload)) + payload


def with_output(model: bytes, name: str) -> bytes:
    """Model z dodatkowym wyjściem: drugie pole `graph` protobuf łączy z pierwszym."""
    value_info = _message(1, name.encode("ascii"))
    return model + _message(7, _message(12, value_info))


def initializers(model: bytes, names: set[str]) -> dict[str, np.ndarray]:
    """Wagi (float32) o podanych nazwach; nazwa jest w polu 8, wymiary w polu 1, dane w polu 4 albo 9."""
    found = {}
    for number, graph in _fields(memoryview(model)):
        if number != 7:
            continue
        for graph_number, tensor in _fields(graph):
            if graph_number != 5:
                continue
            dims, name, raw = [], "", b""
            for tensor_number, value in _fields(tensor):
                if tensor_number == 1:
                    if isinstance(value, int):
                        dims.append(value)
                    else:
                        position = 0
                        while position < len(value):
                            dim, position = _varint(value, position)
                            dims.append(dim)
                elif tensor_number == 8:
                    name = bytes(value).decode()
                elif tensor_number in (4, 9) and not isinstance(value, int):
                    raw = value
            if name in names:
                found[name] = np.frombuffer(raw, dtype="<f4").reshape(dims)
    return found
