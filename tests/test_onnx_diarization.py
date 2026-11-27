"""Silnik rozpoznawania głosów bez PyTorcha (bez modeli i sieci)."""
import hashlib
import io

import pytest

np = pytest.importorskip("numpy")

from rpg_chronicler.transcription import onnx_diarization as engine  # noqa: E402
from rpg_chronicler.transcription import onnx_models  # noqa: E402


def voice(seed, size=engine.EMBEDDING_SIZE):
    return np.random.default_rng(seed).normal(size=size)


def noisy(base, count, seed, noise=0.2):
    return base + np.random.default_rng(seed).normal(scale=noise, size=(count, len(base)))


# --- cechy dźwięku ---

def test_fbank_shape_and_zero_mean():
    features = engine.fbank(np.random.default_rng(1).normal(size=engine.WINDOW).astype(np.float32) * 0.1)
    assert features.shape == (998, 80) and features.dtype == np.float32
    assert np.abs(features.mean(axis=0)).max() < 1e-3


def test_fbank_matches_torchaudio():
    torch = pytest.importorskip("torch")
    kaldi = pytest.importorskip("torchaudio.compliance.kaldi")
    audio = (np.sin(np.arange(32000) * 0.05) * 0.3 + np.random.default_rng(2).normal(size=32000) * 0.05)
    audio = audio.astype(np.float32)
    expected = kaldi.fbank(torch.tensor(audio)[None] * 32768, num_mel_bins=80, dither=0.0, window_type="hamming",
                           use_energy=False).numpy()
    assert np.abs(engine.fbank(audio) - (expected - expected.mean(axis=0))).max() < 1e-2


# --- grupowanie ---

def test_clusters_separate_voices():
    embeddings = np.concatenate([noisy(voice(1), 40, 11), noisy(voice(2), 30, 12), noisy(voice(3), 20, 13)])
    labels = engine.cluster(embeddings)
    assert [len(set(labels[a:b])) for a, b in ((0, 40), (40, 70), (70, 90))] == [1, 1, 1]
    assert len(set(labels)) == 3


def test_small_cluster_joins_nearest_large_one():
    stranger = noisy(voice(1), 2, 15, noise=1.0)
    labels = engine.cluster(np.concatenate([noisy(voice(1), 40, 11), noisy(voice(2), 40, 12), stranger]))
    assert set(labels[-2:]) == {labels[0]}


@pytest.mark.parametrize("threshold", [0.4, 0.7, 1.0])
def test_linkage_matches_scipy(threshold):
    hierarchy = pytest.importorskip("scipy.cluster.hierarchy")
    vectors = engine._unit(np.concatenate([noisy(voice(i, 16), 25, 20 + i, 0.5) for i in range(4)]))
    ours = engine.cut_tree(engine.centroid_linkage(vectors), len(vectors), threshold)
    theirs = hierarchy.fcluster(hierarchy.linkage(vectors, method="centroid"), threshold, criterion="distance")
    assert len(set(zip(ours, theirs))) == len(set(ours)) == len(set(theirs))


@pytest.mark.parametrize("count", [1, 2])
def test_few_embeddings(count):
    assert list(engine.cluster(noisy(voice(1), count, 3))) == [0] * count


# --- wypowiedzi ---

def test_turns_follow_speakers():
    """Minuta: pierwsza połowa jeden głos, druga połowa drugi."""
    count = 51
    segmentation = np.zeros((count, engine.FRAMES, engine.MAX_SPEAKERS), dtype=np.float32)
    embeddings = np.full((count, 3, engine.EMBEDDING_SIZE), np.nan, dtype=np.float32)
    for c in range(count):
        seconds = c + np.arange(engine.FRAMES) * engine.FRAME_STEP
        for speaker, mask in enumerate((seconds < 30, seconds >= 30)):
            if mask.any():
                segmentation[c, mask, speaker] = 1
                embeddings[c, speaker] = noisy(voice(speaker), 1, c)[0]
    turns = engine.build_turns(segmentation, embeddings)
    assert [t.speaker for t in turns] == ["SPEAKER_00", "SPEAKER_01"]
    assert abs(turns[0].end - 30) < 0.2 and abs(turns[1].start - 30) < 0.2 and turns[1].end > 59


def test_silence_gives_no_turns():
    segmentation = np.zeros((5, engine.FRAMES, 3), dtype=np.float32)
    embeddings = np.full((5, 3, engine.EMBEDDING_SIZE), np.nan, dtype=np.float32)
    assert engine.build_turns(segmentation, embeddings) == []


@pytest.mark.parametrize("seconds,windows", [(3, 1), (10, 1), (10.5, 2), (11, 2), (60, 51)])
def test_windows_cover_recording(seconds, windows):
    assert engine._window_count(int(seconds * engine.SAMPLE_RATE)) == windows


def test_diarize_reports_progress_and_handles_short_recording():
    class FakeModels:
        def segment(self, windows):
            return np.ones((len(windows), engine.FRAMES, 3), dtype=np.float32) * [1, 0, 0]

        def frames(self, features):
            return np.ones((len(features), 2560, 125), dtype=np.float32)

        def embed(self, frames, mask):
            return voice(1)
    steps = []
    turns = engine.diarize(FakeModels(), np.zeros(3 * 16000, dtype=np.float32), lambda *step: steps.append(step[0]))
    assert {t.speaker for t in turns} == {"SPEAKER_00"}
    assert set(steps) == {"segmentacja", "cechy głosów", "grupowanie głosów"}


# --- modele ---

def _tensor(name, values, dims):
    raw = np.asarray(values, dtype="<f4").tobytes()
    packed = b"".join(onnx_models._encode_varint(d) for d in dims)
    return onnx_models._message(5, onnx_models._message(1, packed) + onnx_models._message(8, name.encode())
                                + onnx_models._message(9, raw))


def test_weights_are_read_from_model():
    graph = _tensor("inne", [9], [1]) + _tensor("waga", range(300), [100, 3])
    weights = onnx_models.initializers(onnx_models._message(7, graph), {"waga"})
    assert list(weights) == ["waga"] and weights["waga"].shape == (100, 3) and weights["waga"][99, 2] == 299


def test_added_output_is_appended():
    model = onnx_models._message(7, _tensor("waga", [1], [1]))
    extended = onnx_models.with_output(model, "343")
    assert extended.startswith(model) and b"343" in extended[len(model):]
    assert list(onnx_models.initializers(extended, {"waga"})) == ["waga"]


@pytest.fixture
def downloads(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(onnx_models, "models_dir", lambda: tmp_path / "modele")

    def urlopen(request, timeout):
        calls.append(request)
        return io.BytesIO(b"model")
    monkeypatch.setattr(onnx_models.urllib.request, "urlopen", urlopen)
    return calls


def test_model_is_downloaded_once(downloads, tmp_path):
    model = onnx_models.ModelFile("m.onnx", "https://example.org/m", hashlib.sha256(b"model").hexdigest())
    assert onnx_models.ensure_model(model) == b"model" == onnx_models.ensure_model(model)
    assert len(downloads) == 1 and [p.name for p in (tmp_path / "modele").iterdir()] == ["m.onnx"]
    (tmp_path / "modele" / "m.onnx").write_bytes(b"urwany")  # uszkodzony plik - pobierz od nowa
    assert onnx_models.ensure_model(model) == b"model" and len(downloads) == 2


def test_damaged_download_is_rejected(downloads, tmp_path):
    with pytest.raises(onnx_models.ModelDownloadError, match="suma kontrolna"):
        onnx_models.ensure_model(onnx_models.ModelFile("m.onnx", "https://example.org/m", "0" * 64))
    assert not (tmp_path / "modele").exists()


def test_no_internet(monkeypatch, tmp_path):
    monkeypatch.setattr(onnx_models, "models_dir", lambda: tmp_path)

    def urlopen(request, timeout):
        raise onnx_models.urllib.error.URLError("brak sieci")
    monkeypatch.setattr(onnx_models.urllib.request, "urlopen", urlopen)
    with pytest.raises(onnx_models.ModelDownloadError, match="brak sieci"):
        onnx_models.ensure_model(onnx_models.SEGMENTATION)


# --- wybór silnika ---

def test_engine_option_and_default():
    from rpg_chronicler.cli.parser import build_parser
    parser = build_parser()
    assert parser.parse_args(["transcribe"]).engine == parser.parse_args([]).engine == "pyannote"
    assert parser.parse_args(["transcribe", "--glosy", "onnx"]).engine == "onnx"
    assert parser.parse_args(["run", "--glosy", "onnx"]).engine == "onnx"


def test_runner_uses_chosen_engine(monkeypatch):
    for module in ("faster_whisper", "torch", "torchaudio", "torchcodec.decoders", "onnxruntime"):
        pytest.importorskip(module)
    from rpg_chronicler.transcription import runner
    monkeypatch.setattr(engine, "Models", lambda threads: "modele")
    monkeypatch.setattr(engine, "diarize", lambda models, audio, report, threshold: (models, len(audio), threshold))
    import torch
    monkeypatch.setattr(runner, "load_waveform", lambda path: torch.zeros(1, 160))
    assert runner.load_diarizer("onnx")("sesja.m4a", "sesja", 0.65) == ("modele", 160, 0.65)

    class Pipeline:
        params = {"segmentation": {"min_duration_off": 0.0}, "clustering": {"threshold": runner.DIARIZATION_THRESHOLD}}

        def parameters(self, instantiated):
            return {k: dict(v) for k, v in self.params.items()}

        def instantiate(self, params):
            self.params = params
    pipeline = Pipeline()
    monkeypatch.setattr(runner, "load_diarization", lambda: pipeline)
    monkeypatch.setattr(runner, "load_for_diarization", lambda path: path)
    monkeypatch.setattr(runner, "diarize", lambda pipeline, audio, name: (pipeline.params["clustering"]["threshold"],
                                                                         audio, name))
    diarize_session = runner.load_diarizer("pyannote")
    assert diarize_session("sesja.m4a", "sesja", 0.6) == (0.6, "sesja.m4a", "sesja")
    assert diarize_session("sesja.m4a", "sesja") == (runner.DIARIZATION_THRESHOLD, "sesja.m4a", "sesja")


def test_session_threshold_from_option_campaign_or_default():
    for module in ("faster_whisper", "torch", "torchaudio", "torchcodec.decoders"):
        pytest.importorskip(module)
    from types import SimpleNamespace

    from rpg_chronicler.transcription import runner
    session = SimpleNamespace(campaign=SimpleNamespace(voice_threshold=None))
    assert runner.session_threshold(session) == runner.DIARIZATION_THRESHOLD
    session.campaign.voice_threshold = 0.65
    assert runner.session_threshold(session) == 0.65
    assert runner.session_threshold(session, 0.6) == 0.6


def test_threshold_option():
    from rpg_chronicler.cli.parser import build_parser
    parser = build_parser()
    assert parser.parse_args(["transcribe"]).threshold is None
    assert parser.parse_args(["transcribe", "--prog-glosow", "0.65"]).threshold == 0.65
    assert parser.parse_args(["run", "--prog-glosow", "0.6"]).threshold == 0.6


def test_campaign_voice_threshold_in_file(tmp_path):
    from rpg_chronicler import campaigns
    path = str(tmp_path / "kampanie.toml")
    campaigns.save_campaigns({"Warhammer": campaigns.Campaign("Warhammer", "Warhammer", voice_threshold=0.65),
                              "Fallout": campaigns.Campaign("Fallout", "Fallout")}, path)
    loaded = campaigns.load_campaigns(path)
    assert loaded["Warhammer"].voice_threshold == 0.65 and loaded["Fallout"].voice_threshold is None
    fallout, warhammer = open(path, encoding="utf-8").read().split("[Fallout]")[1].split("[Warhammer]")
    assert "prog_glosow" not in fallout and "prog_glosow = 0.65" in warhammer
    assert [campaigns.parse_voice_threshold(v) for v in ("0,65", 0.6, "", None, "abc", 5, True)] == \
        [0.65, 0.6, None, None, None, None, None]


def test_missing_models_stop_transcription_with_message(monkeypatch, capsys, tmp_path):
    for module in ("faster_whisper", "torch", "torchaudio", "torchcodec.decoders"):
        pytest.importorskip(module)
    from types import SimpleNamespace

    from rpg_chronicler.transcription import runner

    def fail(engine_name):
        raise onnx_models.ModelDownloadError("Nie udało się pobrać modelu.")
    monkeypatch.setattr(runner, "load_diarizer", fail)
    monkeypatch.setattr(runner, "TXT_DIR", str(tmp_path))
    session = SimpleNamespace(audio_path="x.m4a", has_transcript=False)
    assert runner.transcribe_sessions([session], "onnx") is False
    assert "[BŁĄD] Nie udało się pobrać modelu." in capsys.readouterr().out
