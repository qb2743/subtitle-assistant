"""Tests for vocal separation (``core/separation/vocal_separator.py``).

Mocks both ``sherpa_onnx`` and the model downloader so no real model download
or real inference happens. Verifies: a missing model triggers the download
path, the separation call parameters, and the output-path convention
(``work/vocal.wav`` + ``work/instrument.wav``).
"""

import sys

import numpy as np
import pytest
import soundfile as sf

import videocaptioner.core.separation.vocal_separator as vs


def _make_wav(path, seconds=1.0, sr=44100):
    """Write a small stereo float32 wav as separation input."""
    samples = np.zeros((int(sr * seconds), 2), dtype=np.float32)
    sf.write(str(path), samples, sr)


def _install_fake_sherpa(monkeypatch, process_recorder=None):
    """Install a fake ``sherpa_onnx`` module into ``sys.modules``."""

    class FakeStem:
        def __init__(self, data):
            self.data = data

    class FakeOutput:
        sample_rate = 44100

        def __init__(self, n_samples):
            self.stems = [
                FakeStem(np.zeros((2, n_samples), dtype=np.float32)),
                FakeStem(np.ones((2, n_samples), dtype=np.float32)),
            ]

    class FakeSeparator:
        def __init__(self, config):
            self.config = config
            self.passed_config = config

        def process(self, *, sample_rate, samples):
            if process_recorder is not None:
                process_recorder["sample_rate"] = sample_rate
                process_recorder["samples_shape"] = samples.shape
            return FakeOutput(samples.shape[1])

    class FakeConfig:
        def validate(self):
            return True

    fake = type(sys)("sherpa_onnx")
    fake.OfflineSourceSeparationConfig = lambda **kw: FakeConfig()
    fake.OfflineSourceSeparationModelConfig = lambda **kw: FakeConfig()
    fake.OfflineSourceSeparationUvrModelConfig = lambda **kw: FakeConfig()
    fake.OfflineSourceSeparation = FakeSeparator
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    return fake


def test_model_missing_triggers_download_and_separates(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(vs, "MODEL_PATH", model_dir)
    downloads = []

    class FakeDownloader:
        def __init__(self, target_dir):
            self.target_dir = target_dir
            self.target_dir.mkdir(parents=True, exist_ok=True)

        def download(self, url, filename=None):
            downloads.append(url)
            (self.target_dir / filename).write_bytes(b"model-content")

    monkeypatch.setattr(vs, "ModelDownloader", FakeDownloader)
    _install_fake_sherpa(monkeypatch)

    wav = tmp_path / "in.wav"
    _make_wav(wav)
    work = tmp_path / "work"
    vocal, instrument = vs.separate_vocals(str(wav), str(work))

    # 模型缺失 → 走下载路径;首个(ModelScope)URL 成功即返回。
    assert len(downloads) == 1
    assert "modelscope" in downloads[0]
    # 输出路径约定:work/vocal.wav 与 work/instrument.wav。
    assert vocal == str(work / "vocal.wav")
    assert instrument == str(work / "instrument.wav")
    # 模型文件已出现在 MODEL_PATH/separate 下。
    assert (model_dir / "separate" / "UVR-MDX-NET-Inst_HQ_4.onnx").exists()


def test_separation_call_args_and_outputs(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(vs, "MODEL_PATH", model_dir)
    # 预置模型文件,避免触发下载。
    sep_dir = model_dir / "separate"
    sep_dir.mkdir(parents=True)
    (sep_dir / "UVR-MDX-NET-Inst_HQ_4.onnx").write_bytes(b"x")

    recorder = {}
    _install_fake_sherpa(monkeypatch, process_recorder=recorder)

    wav = tmp_path / "in.wav"
    _make_wav(wav, seconds=1.0, sr=44100)
    work = tmp_path / "work"
    vocal, instrument = vs.separate_vocals(str(wav), str(work))

    # 分离调用:采样率 44100,样本为 (num_channels, num_samples)。
    assert recorder["sample_rate"] == 44100
    assert recorder["samples_shape"] == (2, 44100)
    # 输出文件均存在且非空。
    assert vocal == str(work / "vocal.wav")
    assert instrument == str(work / "instrument.wav")
    assert (work / "vocal.wav").stat().st_size > 0
    assert (work / "instrument.wav").stat().st_size > 0


def test_missing_model_download_failure_raises_clear_error(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(vs, "MODEL_PATH", model_dir)

    class FailingDownloader:
        def __init__(self, target_dir):
            self.target_dir = target_dir

        def download(self, url, filename=None):
            raise RuntimeError("network down")

    monkeypatch.setattr(vs, "ModelDownloader", FailingDownloader)

    wav = tmp_path / "in.wav"
    _make_wav(wav)
    with pytest.raises(RuntimeError) as excinfo:
        vs.separate_vocals(str(wav), str(tmp_path / "work"))
    msg = str(excinfo.value)
    assert "下载失败" in msg
    assert "手动下载" in msg or "放置到目录" in msg
    assert "UVR-MDX-NET-Inst_HQ_4.onnx" in msg


def test_missing_sherpa_raises_clear_error(monkeypatch, tmp_path):
    model_dir = tmp_path / "models"
    monkeypatch.setattr(vs, "MODEL_PATH", model_dir)
    sep_dir = model_dir / "separate"
    sep_dir.mkdir(parents=True)
    (sep_dir / "UVR-MDX-NET-Inst_HQ_4.onnx").write_bytes(b"x")

    # 移除 sherpa_onnx 与 soundfile 模块,模拟未安装依赖。
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    wav = tmp_path / "in.wav"
    _make_wav(wav)
    with pytest.raises(RuntimeError) as excinfo:
        vs.separate_vocals(str(wav), str(tmp_path / "work"))
    assert "sherpa-onnx" in str(excinfo.value)
