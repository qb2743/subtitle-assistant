"""Tests for the reusable ModelDownloader (2.1)."""

import zipfile

import pytest

from videocaptioner.core.utils.model_downloader import (
    FASTER_WHISPER_MODELS,
    FASTER_WHISPER_PROGRAMS,
    ModelDownloader,
    _hf_mirror,
    get_faster_whisper_model_repo,
    get_faster_whisper_program_url,
)


class _FakeResponse:
    """Fake requests streaming response."""

    def __init__(self, chunks: list[bytes], total: int | None = None, raise_for: Exception | None = None):
        self._chunks = chunks
        self.headers = {"content-length": str(total if total is not None else sum(len(c) for c in chunks))}
        self._raise = raise_for

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c


def _patch_get(monkeypatch, responses: dict[str, _FakeResponse]):
    """Make requests.get return the FakeResponse for the given URL, else raise."""

    def _fake_get(url, stream=False, timeout=30):
        if url in responses:
            return responses[url]
        raise ConnectionError(f"no fake for {url}")

    monkeypatch.setattr("videocaptioner.core.utils.model_downloader.requests.get", _fake_get)


def test_download_writes_file_and_reports_progress(tmp_path, monkeypatch):
    payload = b"HELLO-MODEL-DATA" * 4
    _patch_get(
        monkeypatch,
        {"https://example.com/model.bin": _FakeResponse([payload[:16], payload[16:]], total=len(payload))},
    )
    progress: list = []
    dl = ModelDownloader(tmp_path)
    path = dl.download("https://example.com/model.bin", progress=lambda p, s: progress.append((p, s)))

    assert path == tmp_path / "model.bin"
    assert path.read_bytes() == payload
    # Progress moved from 0 toward 100.
    assert progress[0][0] == 0
    assert progress[-1][0] > 0


def test_download_hf_mirror_fallback(tmp_path, monkeypatch):
    """A failing huggingface.co URL retries against hf-mirror.com and succeeds."""
    payload = b"model-bytes"
    _patch_get(
        monkeypatch,
        {
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin": _FakeResponse(
                [], raise_for=ConnectionError("blocked")
            ),
            "https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin": _FakeResponse(
                [payload], total=len(payload)
            ),
        },
    )
    dl = ModelDownloader(tmp_path)
    path = dl.download("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin")
    assert path.read_bytes() == payload


def test_download_all_fail_raises(tmp_path, monkeypatch):
    _patch_get(monkeypatch, {})
    dl = ModelDownloader(tmp_path)
    with pytest.raises(RuntimeError, match="Failed to download"):
        dl.download("https://huggingface.co/x/y.bin")  # HF URL -> tries mirror too, both fail


def test_cancel_aborts_download(tmp_path, monkeypatch):
    _patch_get(
        monkeypatch,
        {"https://example.com/big.bin": _FakeResponse([b"chunk"] * 1000, total=10000)},
    )
    dl = ModelDownloader(tmp_path)

    def _progress(p, s):
        if p > 5:  # cancel mid-stream
            dl.cancel()

    with pytest.raises(RuntimeError, match="cancelled"):
        dl.download("https://example.com/big.bin", progress=_progress)
    # Temp file cleaned up, no final file.
    assert not (tmp_path / "big.bin").exists()
    assert not (tmp_path / "big.bin.tmp").exists()


def test_verify_size(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"12345")
    assert ModelDownloader.verify(f, expected_size=5) is True
    assert ModelDownloader.verify(f, expected_size=99) is False
    assert ModelDownloader.verify(tmp_path / "missing.bin") is False


def test_extract_zip(tmp_path):
    archive = tmp_path / "pkg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("inner/file.txt", "hello")
        zf.writestr("readme.txt", "hi")
    out = tmp_path / "out"
    ModelDownloader.extract(archive, out)
    assert (out / "inner" / "file.txt").read_text() == "hello"
    assert (out / "readme.txt").read_text() == "hi"
    assert not archive.exists()  # archive removed after extraction


def test_extract_unsupported_type(tmp_path):
    f = tmp_path / "x.tar"
    f.write_bytes(b"nope")
    with pytest.raises(ValueError, match="Unsupported archive type"):
        ModelDownloader.extract(f, tmp_path / "out", remove_archive=False)


def test_real_url_constants_present():
    # Faster Whisper program URLs (real ModelScope links).
    assert any("modelscope.cn" in p["url"] for p in FASTER_WHISPER_PROGRAMS)
    assert get_faster_whisper_program_url("CPU").endswith("whisper-faster.exe")
    # Faster Whisper model repos (HuggingFace + ModelScope ids).
    assert any(m["value"] == "faster-whisper-large-v3" for m in FASTER_WHISPER_MODELS)
    assert get_faster_whisper_model_repo("faster-whisper-tiny") == "pengzhendong/faster-whisper-tiny"
    assert _hf_mirror("https://huggingface.co/a/b") == "https://hf-mirror.com/a/b"
