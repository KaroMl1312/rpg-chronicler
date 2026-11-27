"""Rozpoznawanie głosów bez PyTorcha: onnxruntime + numpy (drugi silnik obok pyannote).

Te same sieci i te same kroki co pyannote/speaker-diarization-3.1: segmentacja okien 10 s co 1 s, odcisk każdego
mówcy okna, grupowanie odcisków i złożenie okien w wypowiedzi. Różnica: ResNet liczy cechy okna raz (a nie osobno
dla każdego mówcy), a maska mówcy wchodzi dopiero przy uśrednianiu - stąd ok. 6 razy krótszy czas.
"""
from typing import Callable

import numpy as np

from .merge import Turn

SAMPLE_RATE = 16000
WINDOW = 10 * SAMPLE_RATE
STEP = SAMPLE_RATE
FRAMES, MAX_SPEAKERS = 589, 3               # ramki okna i mówcy w oknie (model segmentacji)
FRAME_DURATION, FRAME_STEP = 991 / SAMPLE_RATE, 270 / SAMPLE_RATE
# Klasy segmentacji: nikt, jeden z trzech mówców, dwóch naraz
POWERSET = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1]], dtype=np.float32)
# Parametry grupowania z pyannote/speaker-diarization-3.1
THRESHOLD = 0.7045654963945799
MIN_CLUSTER_SIZE = 12
EMBEDDING_SIZE = 256
SEGMENTATION_BATCH, EMBEDDING_BATCH = 32, 8

Progress = Callable[[str, int, int], None]


# --- cechy dźwięku (jak kaldi/torchaudio: 80 filtrów mel, okno Hamminga) ---

FBANK_FRAME, FBANK_STEP, FBANK_FFT, MEL_BINS = 400, 160, 512, 80
_HAMMING = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(FBANK_FRAME) / (FBANK_FRAME - 1))


def _mel_filters() -> np.ndarray:
    def mel(hz):
        return 1127.0 * np.log(1.0 + hz / 700.0)
    low, high = mel(20.0), mel(SAMPLE_RATE / 2)
    edges = low + (high - low) / (MEL_BINS + 1) * np.arange(MEL_BINS + 2)
    bins = mel(np.arange(FBANK_FFT // 2) * SAMPLE_RATE / FBANK_FFT)
    left, center, right = edges[:-2, None], edges[1:-1, None], edges[2:, None]
    return np.maximum(0.0, np.minimum((bins - left) / (center - left), (right - bins) / (right - center)))


_MEL = _mel_filters()


def fbank(audio: np.ndarray) -> np.ndarray:
    """Cechy (ramki, 80) z odjętą średnią."""
    frames = np.lib.stride_tricks.sliding_window_view(audio.astype(np.float64) * 32768, FBANK_FRAME)[::FBANK_STEP]
    frames = frames - frames.mean(axis=1, keepdims=True)
    emphasized = frames.copy()
    emphasized[:, 1:] -= 0.97 * frames[:, :-1]
    emphasized[:, 0] -= 0.97 * frames[:, 0]
    power = np.abs(np.fft.rfft(emphasized * _HAMMING, FBANK_FFT, axis=1)[:, :-1]) ** 2
    features = np.log(np.maximum(power @ _MEL.T, np.finfo(np.float32).eps))
    return (features - features.mean(axis=0)).astype(np.float32)


# --- sieci ---

class Models:
    def __init__(self, threads: int):
        import onnxruntime

        from .onnx_models import EMBEDDING, FRAMES_OUTPUT, SEGMENTATION, ensure_model, initializers, with_output

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.log_severity_level = 3

        def session(model: bytes):
            return onnxruntime.InferenceSession(model, options, providers=["CPUExecutionProvider"])

        segmentation, embedding = ensure_model(SEGMENTATION), ensure_model(EMBEDDING)
        weights = initializers(embedding, {"model.seg_1.weight", "model.seg_1.bias", "mean_vec"})
        self.weight, self.bias = weights["model.seg_1.weight"], weights["model.seg_1.bias"]
        self.mean = weights["mean_vec"]
        self._frames_output = FRAMES_OUTPUT
        self._segmentation = session(segmentation)
        self._embedding = session(with_output(embedding, FRAMES_OUTPUT))

    def segment(self, windows: np.ndarray) -> np.ndarray:
        """Aktywność mówców (okna, ramki, 3) dla okien (okna, próbki)."""
        name = self._segmentation.get_inputs()[0].name
        return POWERSET[self._segmentation.run(None, {name: windows[:, None]})[0].argmax(-1)]

    def frames(self, features: np.ndarray) -> np.ndarray:
        """Cechy ramek (okna, 2560, czas) - wyjście ResNet-u przed uśrednianiem."""
        name = self._embedding.get_inputs()[0].name
        output = self._embedding.run([self._frames_output], {name: features})[0]
        return output.reshape(len(features), 2560, -1)

    def embed(self, frames: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Odcisk głosu z ramek jednego okna ważonych aktywnością mówcy (średnia i odchylenie)."""
        total = mask.sum() + 1e-8
        mean = frames @ mask / total
        variance = ((frames - mean[:, None]) ** 2 @ mask) / (total - (mask ** 2).sum() / total + 1e-8)
        statistics = np.concatenate([mean, np.sqrt(np.maximum(variance, 0))])
        return self.weight @ statistics + self.bias - self.mean


# --- grupowanie odcisków ---

def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-9)


def centroid_linkage(vectors: np.ndarray) -> list[tuple[int, int, float]]:
    """Łączenie najbliższych grup wg odległości środków (jak scipy `linkage(method="centroid")`)."""
    n = len(vectors)
    vectors = vectors.astype(np.float32)
    distances = vectors @ vectors.T
    distances *= -2
    distances += 2
    np.maximum(distances, 0, out=distances)
    np.fill_diagonal(distances, np.inf)
    sizes, nodes, alive = np.ones(n), np.arange(n), np.ones(n, dtype=bool)
    nearest = distances.argmin(axis=1)
    nearest_distance = distances[np.arange(n), nearest]
    merges = []
    for step in range(n - 1):
        i = int(nearest_distance.argmin())
        j = int(nearest[i])
        distance = float(nearest_distance[i])
        size_i, size_j = sizes[i], sizes[j]
        size = size_i + size_j
        merges.append((int(nodes[i]), int(nodes[j]), float(np.sqrt(max(distance, 0)))))
        row = ((size_i * distances[i] + size_j * distances[j]) / size
               - size_i * size_j * distance / size ** 2).astype(np.float32)
        row = np.maximum(row, 0)
        alive[j] = False
        row[~alive] = np.inf
        row[i] = np.inf
        distances[i], distances[:, i] = row, row
        distances[j], distances[:, j] = np.inf, np.inf
        nearest_distance[j] = np.inf
        sizes[i], nodes[i] = size, n + step
        nearest[i] = row.argmin()
        nearest_distance[i] = row[nearest[i]]
        # sąsiadem połączonych grup był ktoś inny - trzeba poszukać od nowa
        outdated = alive & ((nearest == i) | (nearest == j))
        outdated[i] = False
        for k in np.nonzero(outdated)[0]:
            nearest[k] = distances[k].argmin()
            nearest_distance[k] = distances[k, nearest[k]]
        closer = alive & (row < nearest_distance)
        closer[i] = False
        nearest[closer] = i
        nearest_distance[closer] = row[closer]
    return merges


def cut_tree(merges: list[tuple[int, int, float]], n: int, threshold: float) -> np.ndarray:
    """Numery grup po przecięciu drzewa (jak scipy `fcluster(criterion="distance")`)."""
    highest = [0.0] * n
    for a, b, distance in merges:
        highest.append(max(distance, highest[a], highest[b]))
    labels, count = np.full(n, -1), 0
    stack = [2 * n - 2]
    while stack:
        node = stack.pop()
        if node >= n and highest[node] > threshold:
            stack += merges[node - n][:2]
            continue
        members = [node]
        while members:
            member = members.pop()
            if member < n:
                labels[member] = count
            else:
                members += merges[member - n][:2]
        count += 1
    return labels


def cluster(embeddings: np.ndarray, threshold: float = THRESHOLD) -> np.ndarray:
    """Numer mówcy każdego odcisku; małe grupy dołączają do najbliższej dużej."""
    n = len(embeddings)
    vectors = _unit(embeddings.astype(np.float64))
    labels = cut_tree(centroid_linkage(vectors), n, threshold)
    minimum = min(MIN_CLUSTER_SIZE, max(1, round(0.1 * n)))
    numbers, counts = np.unique(labels, return_counts=True)
    large, small = numbers[counts >= minimum], numbers[counts < minimum]
    if len(large) == 0:
        return np.zeros(n, dtype=int)
    if len(small):
        centers = _unit(np.array([vectors[labels == k].mean(axis=0) for k in large]))
        targets = {k: large[(centers @ _unit(vectors[labels == k].mean(axis=0))).argmax()] for k in small}
        for k, target in targets.items():
            labels[labels == k] = target
    return np.unique(labels, return_inverse=True)[1]


# --- całość ---

def _window(audio: np.ndarray, index: int) -> np.ndarray:
    window = audio[index * STEP:index * STEP + WINDOW]
    return np.pad(window, (0, WINDOW - len(window)))


def _window_count(samples: int) -> int:
    if samples <= WINDOW:
        return 1
    return -(-(samples - WINDOW) // STEP) + 1


def _embeddings(models: Models, audio: np.ndarray, segmentation: np.ndarray, progress: Progress) -> np.ndarray:
    count = len(segmentation)
    alone = segmentation * (segmentation.sum(axis=2, keepdims=True) < 2)
    # odcisk tylko z ramek bez nakładających się głosów, chyba że prawie ich nie ma
    weights = np.where(alone.sum(axis=1, keepdims=True) > 3, alone, segmentation)
    embeddings = np.full((count, MAX_SPEAKERS, EMBEDDING_SIZE), np.nan, dtype=np.float32)
    for start in range(0, count, EMBEDDING_BATCH):
        progress("cechy głosów", start, count)
        windows = [c for c in range(start, min(count, start + EMBEDDING_BATCH)) if segmentation[c].any()]
        if not windows:
            continue
        frames = models.frames(np.stack([fbank(_window(audio, c)) for c in windows]))
        index = np.arange(frames.shape[2]) * FRAMES // frames.shape[2]
        for c, window_frames in zip(windows, frames):
            for speaker in range(MAX_SPEAKERS):
                mask = weights[c, index, speaker]
                if mask.any():
                    embeddings[c, speaker] = models.embed(window_frames, mask)
    return embeddings


def build_turns(segmentation: np.ndarray, embeddings: np.ndarray, threshold: float = THRESHOLD) -> list[Turn]:
    """Wypowiedzi mówców całego nagrania z segmentacji okien i odcisków ich mówców."""
    count = len(segmentation)
    single = segmentation.sum(axis=2, keepdims=True) == 1
    # do grupowania tylko mówcy, którzy przez co najmniej 20% okna mówią sami
    active = (segmentation * single).sum(axis=1) >= 0.2 * segmentation.shape[1]
    windows, speakers = np.nonzero(active & ~np.isnan(embeddings).any(axis=2))
    if len(windows) == 0:  # bardzo krótkie albo ciche nagranie
        windows, speakers = np.nonzero(~np.isnan(embeddings).any(axis=2))
        if len(windows) == 0:
            return []
    training = embeddings[windows, speakers]
    labels = cluster(training, threshold)
    total = int(labels.max()) + 1
    centers = _unit(np.array([training[labels == k].mean(axis=0) for k in range(total)]))
    assigned = (_unit(np.nan_to_num(embeddings)).reshape(-1, EMBEDDING_SIZE) @ centers.T).argmax(axis=1)
    assigned = assigned.reshape(count, MAX_SPEAKERS)
    assigned[segmentation.sum(axis=1) == 0] = -1

    length = round((10 + (count - 1)) / FRAME_STEP) + 1
    activity = np.zeros((length, total), dtype=np.float32)
    speaking = np.zeros(length, dtype=np.float32)
    overlaps = np.zeros(length, dtype=np.float32)
    for c in range(count):
        start = round(c / FRAME_STEP)
        end = min(length, start + FRAMES)
        for k in set(assigned[c].tolist()) - {-1}:
            activity[start:end, k] += segmentation[c][:end - start, assigned[c] == k].max(axis=1)
        speaking[start:end] += segmentation[c][:end - start].sum(axis=1)
        overlaps[start:end] += 1
    # tylu mówców naraz, ilu średnio słyszą okna; wybierani ci, których okien jest najwięcej
    speaker_count = np.rint(speaking / np.maximum(overlaps, 1e-12)).astype(int)
    order = np.argsort(-activity, axis=1)
    chosen = np.zeros((length, total), dtype=bool)
    for rank in range(min(total, MAX_SPEAKERS)):
        frames = np.nonzero(speaker_count > rank)[0]
        chosen[frames, order[frames, rank]] = True

    spans = []
    for k in range(total):
        edges = np.flatnonzero(np.diff(np.concatenate([[0], chosen[:, k].astype(int), [0]])))
        spans += [(start * FRAME_STEP + FRAME_DURATION / 2, min(end, length - 1) * FRAME_STEP + FRAME_DURATION / 2, k)
                  for start, end in edges.reshape(-1, 2).tolist()]
    spans.sort()
    numbers: dict[int, int] = {}  # etykiety w kolejności pierwszych wypowiedzi
    return [Turn(start, end, f"SPEAKER_{numbers.setdefault(k, len(numbers)):02d}") for start, end, k in spans]


def diarize(models: Models, audio: np.ndarray, progress: Progress = lambda step, done, total: None,
            threshold: float = THRESHOLD) -> list[Turn]:
    """Wypowiedzi mówców z nagrania mono 16 kHz (float32)."""
    count = _window_count(len(audio))
    segmentation = np.zeros((count, FRAMES, MAX_SPEAKERS), dtype=np.float32)
    for start in range(0, count, SEGMENTATION_BATCH):
        progress("segmentacja", start, count)
        windows = range(start, min(count, start + SEGMENTATION_BATCH))
        segmentation[start:start + SEGMENTATION_BATCH] = models.segment(np.stack([_window(audio, c) for c in windows]))
    embeddings = _embeddings(models, audio, segmentation, progress)
    progress("grupowanie głosów", 0, 1)
    return build_turns(segmentation, embeddings, threshold)
