"""Tests for ``core/diarization/speaker_diarizer.py``.

Mocks both ``sherpa_onnx`` and the model downloader so no real model download
or real inference happens. Verifies: a missing model triggers the download
path, the result structure (normalized ``{"start","end","speaker"}`` in
seconds), language select (zh → 3dspeaker, en → titanet, multi → SimAMResNet), and the
``num_clusters`` passed to FastClustering.
"""

import sys

import numpy as np
import pytest

import videocaptioner.core.diarization.speaker_diarizer as sd


def _install_fake_sherpa(monkeypatch, raw_segments, cluster_calls=None):
    """Install a fake ``sherpa_onnx`` module into ``sys.modules``.

    ``raw_segments``: list of (start, end, speaker_index) tuples returned by
    ``process(...).sort_by_start_time()``.
    """

    class FakeDiarItem:
        def __init__(self, start, end, speaker):
            self.start = start
            self.end = end
            self.speaker = speaker

    class FakeResultList:
        def __init__(self, items):
            self.items = items

        def sort_by_start_time(self):
            return list(self.items)

    class FakeDiar:
        sample_rate = 16000

        def __init__(self, config):
            self.config = config

        def process(self, samples, callback=None):
            if callback is not None:
                callback(1, 1)
            return FakeResultList(
                [FakeDiarItem(s, e, k) for s, e, k in raw_segments]
            )

    class FakePyannoteConfig:
        def __init__(self, **kw):
            self.kw = kw

        def validate(self):
            return True

    class FakeClusterConfig:
        def __init__(self, **kw):
            if cluster_calls is not None:
                cluster_calls.append(kw)

        def validate(self):
            return True

    fake = type(sys)("sherpa_onnx")
    fake.OfflineSpeakerDiarizationConfig = FakePyannoteConfig
    fake.OfflineSpeakerSegmentationModelConfig = FakePyannoteConfig
    fake.OfflineSpeakerSegmentationPyannoteModelConfig = FakePyannoteConfig
    fake.SpeakerEmbeddingExtractorConfig = FakePyannoteConfig
    fake.FastClusteringConfig = FakeClusterConfig
    fake.OfflineSpeakerDiarization = FakeDiar
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    return fake


def _fake_audio(monkeypatch, sr=16000):
    monkeypatch.setattr(
        sd, "_load_audio_mono", lambda path, target_sr: (np.zeros(target_sr, dtype=np.float32), target_sr)
    )


def test_missing_models_trigger_download_and_diarize(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(sd, "MODEL_PATH", model_dir)
    downloads = []

    class FakeDownloader:
        def __init__(self, target_dir):
            self.target_dir = target_dir
            self.target_dir.mkdir(parents=True, exist_ok=True)

        def download(self, url, filename=None):
            downloads.append(url)
            (self.target_dir / filename).write_bytes(b"model-content")

    monkeypatch.setattr(sd, "ModelDownloader", FakeDownloader)
    _install_fake_sherpa(monkeypatch, [(0.0, 0.9, 0), (0.9, 1.8, 1)])
    _fake_audio(monkeypatch)

    out = sd.diarize(str(tmp_path / "in.wav"))

    # 两个模型缺失(segmentation + embedding zh)→ 下载两条,首个则 ModelScope 优先。
    assert len(downloads) == 2
    assert "seg_model.onnx" in downloads[0]
    assert "3dspeaker" in downloads[1]
    # 结果已标准化:speaker 重映射为 spk0/spk1,start/end 单位为秒。
    assert out == [
        {"start": 0.0, "end": 0.9, "speaker": "spk0"},
        {"start": 0.9, "end": 1.8, "speaker": "spk1"},
    ]


def test_diarize_with_existing_models_and_en_language(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(sd, "MODEL_PATH", model_dir)
    dia_dir = model_dir / "diarization"
    dia_dir.mkdir(parents=True)
    (dia_dir / "seg_model.onnx").write_bytes(b"x")
    (dia_dir / "nemo_en_titanet_small.onnx").write_bytes(b"x")

    downloaded = []

    class FakeDownloader:
        def __init__(self, target_dir):
            pass

        def download(self, url, filename=None):
            downloaded.append(url)

    monkeypatch.setattr(sd, "ModelDownloader", FakeDownloader)
    _install_fake_sherpa(monkeypatch, [(0.0, 1.0, 0)])
    _fake_audio(monkeypatch)

    out = sd.diarize(str(tmp_path / "in.wav"), language="en")

    assert downloaded == []  # 模型已存在,不触发下载。
    assert out == [{"start": 0.0, "end": 1.0, "speaker": "spk0"}]


def test_diarize_with_existing_multilingual_model(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(sd, "MODEL_PATH", model_dir)
    dia_dir = model_dir / "diarization"
    dia_dir.mkdir(parents=True)
    (dia_dir / "seg_model.onnx").write_bytes(b"x")
    (dia_dir / "tidyvoicex_samresnet34.onnx").write_bytes(b"x")

    downloads = []

    class FakeDownloader:
        def __init__(self, target_dir):
            pass

        def download(self, url, filename=None):
            downloads.append(url)

    monkeypatch.setattr(sd, "ModelDownloader", FakeDownloader)
    _install_fake_sherpa(monkeypatch, [(0.0, 1.0, 0)])
    _fake_audio(monkeypatch)

    out = sd.diarize(str(tmp_path / "in.wav"), language="multi")

    assert downloads == []
    assert out == [{"start": 0.0, "end": 1.0, "speaker": "spk0"}]


def test_diarize_passes_num_speakers_to_fast_clustering(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(sd, "MODEL_PATH", model_dir)
    dia_dir = model_dir / "diarization"
    dia_dir.mkdir(parents=True)
    (dia_dir / "seg_model.onnx").write_bytes(b"x")
    (dia_dir / "3dspeaker_speech_eres2net_large_sv_zh-cn_3dspeaker_16k.onnx").write_bytes(b"x")

    cluster_calls = []
    _install_fake_sherpa(monkeypatch, [(0.0, 1.0, 0)], cluster_calls=cluster_calls)
    _fake_audio(monkeypatch)

    sd.diarize(str(tmp_path / "in.wav"), num_speakers=2)

    assert cluster_calls and cluster_calls[0].get("num_clusters") == 2


def test_diarize_subprocess_returns_worker_result(monkeypatch):
    expected = [{"start": 0.0, "end": 1.0, "speaker": "spk0"}]
    monkeypatch.setattr(sd, "diarize", lambda *args, **kwargs: expected)

    class InlineProcess:
        def __init__(self, target, args):
            self.target = target
            self.args = args
            self.exitcode = None

        def start(self):
            self.target(*self.args)
            self.exitcode = 0

        def join(self):
            pass

        def close(self):
            pass

    class InlineContext:
        @staticmethod
        def Process(target, args):
            return InlineProcess(target, args)

    monkeypatch.setattr(sd.multiprocessing, "get_context", lambda _name: InlineContext())

    assert sd._diarize_in_subprocess("input.mp4", 0, "multi") == expected


def test_diarize_subprocess_terminates_when_cancelled(monkeypatch):
    state = {"terminated": False, "closed": False}

    class BlockingProcess:
        daemon = False
        exitcode = None

        def start(self):
            pass

        def is_alive(self):
            return not state["terminated"]

        def join(self, timeout=None):
            pass

        def terminate(self):
            state["terminated"] = True

        def close(self):
            state["closed"] = True

    class BlockingContext:
        @staticmethod
        def Process(target, args):
            return BlockingProcess()

    monkeypatch.setattr(sd.multiprocessing, "get_context", lambda _name: BlockingContext())

    with pytest.raises(RuntimeError, match="任务已取消"):
        sd._diarize_in_subprocess("input.mp4", 0, "multi", cancelled=lambda: True)

    assert state == {"terminated": True, "closed": True}


def test_native_model_path_uses_ascii_relative_path(monkeypatch, tmp_path):
    project = tmp_path / "中文项目"
    model = project / "AppData" / "models" / "diarization" / "seg_model.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    monkeypatch.setattr(sd.sys, "platform", "win32")
    monkeypatch.chdir(project)

    assert sd._native_model_path(model) == str(
        model.relative_to(project)
    )


def test_diarize_missing_model_download_failure_raises_clear_error(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(sd, "MODEL_PATH", model_dir)

    class FailingDownloader:
        def __init__(self, target_dir):
            self.target_dir = target_dir

        def download(self, url, filename=None):
            raise RuntimeError("network down")

    monkeypatch.setattr(sd, "ModelDownloader", FailingDownloader)

    with pytest.raises(RuntimeError) as excinfo:
        sd.diarize(str(tmp_path / "in.wav"))
    msg = str(excinfo.value)
    assert "下载失败" in msg
    assert "seg_model.onnx" in msg
    assert "放置到目录" in msg


def test_load_audio_mono_with_real_wav(tmp_path):
    """``_load_audio_mono`` 用 ffmpeg 把 44.1k 立体声降采样为 16k 单声道。"""
    import soundfile as sf

    sr_in = 44100
    samples = np.zeros((sr_in * 1, 2), dtype=np.float32)
    wav = tmp_path / "in.wav"
    sf.write(str(wav), samples, sr_in)

    audio, sr = sd._load_audio_mono(str(wav), 16000)
    assert sr == 16000
    assert audio.ndim == 1
    assert audio.shape[0] == 16000
