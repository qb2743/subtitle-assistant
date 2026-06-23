"""Generic model/asset downloader (reusable, non-GUI).

Consolidates VideoCaptioner's download logic (requests streaming + aria2c +
zip/7z extraction + HuggingFace mirror fallback) into a single non-GUI
utility that the dubbing / local-TTS / ASR code can reuse.

Real download URLs for Faster Whisper (ported from
``ui/components/FasterWhisperSettingWidget.py``) are exposed as constants so
the downloader is usable out of the box:

- ``FASTER_WHISPER_PROGRAMS`` — the faster-whisper binary (.7z GPU / .exe CPU)
  hosted on ModelScope.
- ``FASTER_WHISPER_MODELS`` — whisper model repos on HuggingFace (+ ModelScope
  mirror ids); downloaded via ``download_modelscope_repo``.
"""

import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("model_downloader")

ProgressCallback = Callable[[float, str], None]

_HF_HOST = "huggingface.co"
_HF_MIRROR = "hf-mirror.com"

# Real Faster Whisper program download URLs (ModelScope).
FASTER_WHISPER_PROGRAMS: list[dict] = [
    {
        "label": "GPU (cuda) + CPU",
        "value": "Faster-Whisper-XXL_r245.2_windows.7z",
        "size": "1.35 GB",
        "url": "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/Faster-Whisper-XXL_r245.2_windows.7z",
    },
    {
        "label": "CPU",
        "value": "whisper-faster.exe",
        "size": "78.7 MB",
        "url": "https://modelscope.cn/models/bkfengg/whisper-cpp/resolve/master/whisper-faster.exe",
    },
]

# Real Faster Whisper model repos (HuggingFace + ModelScope mirror id).
FASTER_WHISPER_MODELS: list[dict] = [
    {"label": "Tiny", "value": "faster-whisper-tiny",
     "hf": "https://huggingface.co/Systran/faster-whisper-tiny", "modelscope": "pengzhendong/faster-whisper-tiny"},
    {"label": "Base", "value": "faster-whisper-base",
     "hf": "https://huggingface.co/Systran/faster-whisper-base", "modelscope": "pengzhendong/faster-whisper-base"},
    {"label": "Small", "value": "faster-whisper-small",
     "hf": "https://huggingface.co/Systran/faster-whisper-small", "modelscope": "pengzhendong/faster-whisper-small"},
    {"label": "Medium", "value": "faster-whisper-medium",
     "hf": "https://huggingface.co/Systran/faster-whisper-medium", "modelscope": "pengzhendong/faster-whisper-medium"},
    {"label": "Large-v1", "value": "faster-whisper-large-v1",
     "hf": "https://huggingface.co/Systran/faster-whisper-large-v1", "modelscope": "pengzhendong/faster-whisper-large-v1"},
    {"label": "Large-v2", "value": "faster-whisper-large-v2",
     "hf": "https://huggingface.co/Systran/faster-whisper-large-v2", "modelscope": "pengzhendong/faster-whisper-large-v2"},
    {"label": "Large-v3", "value": "faster-whisper-large-v3",
     "hf": "https://huggingface.co/Systran/faster-whisper-large-v3", "modelscope": "pengzhendong/faster-whisper-large-v3"},
    {"label": "Large-v3-turbo", "value": "faster-whisper-large-v3-turbo",
     "hf": "https://huggingface.co/Systran/faster-whisper-large-v3-turbo", "modelscope": "pengzhendong/faster-whisper-large-v3-turbo"},
]


def _format_size(bytes_size: float) -> str:
    size = float(bytes_size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _hf_mirror(url: str) -> str:
    """Return the hf-mirror.com equivalent of a huggingface.co URL."""
    return url.replace(_HF_HOST, _HF_MIRROR)


class ModelDownloader:
    """Download, verify, and extract a model/asset file (non-GUI).

    Uses requests streaming by default. For ``huggingface.co`` URLs, falls back
    to ``hf-mirror.com`` on failure. Extraction supports ``.zip`` (stdlib) and
    ``.7z`` (via the ``7z`` binary).
    """

    CHUNK_SIZE = 8192

    def __init__(self, target_dir: str | Path):
        self.target_dir = Path(target_dir)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self._cancelled = False

    def cancel(self) -> None:
        """Mark the in-flight download as cancelled."""
        self._cancelled = True

    # -- download ---------------------------------------------------------
    def download(
        self,
        url: str,
        filename: Optional[str] = None,
        progress: Optional[ProgressCallback] = None,
        timeout: int = 30,
    ) -> Path:
        """Stream-download ``url`` into ``target_dir/filename``.

        For huggingface.co URLs, retries against hf-mirror.com on failure.
        Returns the saved Path; raises ``RuntimeError`` if all attempts fail.
        """
        name = filename or url.rsplit("/", 1)[-1].split("?")[0] or "download"
        save_path = self.target_dir / name
        cb = progress or (lambda _p, _s: None)

        urls = [url]
        if _HF_HOST in url:
            urls.append(_hf_mirror(url))

        last_error: Exception | None = None
        for try_url in urls:
            if self._cancelled:
                raise RuntimeError("download cancelled")
            try:
                self._download_one(try_url, save_path, cb, timeout)
                return save_path
            except Exception as exc:
                last_error = exc
                logger.warning("Download from %s failed: %s", try_url, exc)
                if self._cancelled:
                    raise
        raise RuntimeError(f"Failed to download {url}: {last_error}")

    def _download_one(
        self,
        url: str,
        save_path: Path,
        cb: ProgressCallback,
        timeout: int,
    ) -> None:
        cb(0, "正在连接...")
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        temp = save_path.with_suffix(save_path.suffix + ".tmp")
        try:
            with temp.open("wb") as f:
                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if self._cancelled:
                        raise RuntimeError("download cancelled")
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        cb(downloaded / total * 100, f"已下载: {_format_size(downloaded)} / {_format_size(total)}")
                    else:
                        cb(-1, f"已下载: {_format_size(downloaded)}")
            shutil.move(str(temp), str(save_path))
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)

    def download_modelscope_repo(self, model_id: str) -> Path:
        """Download a ModelScope model repo into ``target_dir`` (uses modelscope)."""
        try:
            from modelscope.hub.snapshot_download import snapshot_download
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The 'modelscope' package is required to download model repos. "
                "Install it with `pip install modelscope`."
            ) from exc
        logger.info("Downloading ModelScope repo %s -> %s", model_id, self.target_dir)
        local = snapshot_download(model_id, local_dir=str(self.target_dir))
        return Path(local)

    # -- verify -----------------------------------------------------------
    @staticmethod
    def verify(path: str | Path, expected_size: Optional[int] = None) -> bool:
        """Return True if ``path`` exists and (optionally) matches ``expected_size``."""
        p = Path(path)
        if not p.is_file():
            return False
        if expected_size is not None and p.stat().st_size != expected_size:
            return False
        return True

    # -- extract ----------------------------------------------------------
    @staticmethod
    def extract(
        archive_path: str | Path,
        target_dir: Optional[str | Path] = None,
        remove_archive: bool = True,
    ) -> Path:
        """Extract a ``.zip`` (stdlib) or ``.7z`` (via 7z binary). Returns target dir."""
        archive = Path(archive_path)
        out = Path(target_dir) if target_dir else archive.parent
        out.mkdir(parents=True, exist_ok=True)
        suffix = archive.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(out)
        elif suffix == ".7z":
            subprocess.run(
                ["7z", "x", str(archive), f"-o{out}", "-y"],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            raise ValueError(f"Unsupported archive type: {suffix}")
        if remove_archive:
            archive.unlink(missing_ok=True)
        return out


def get_faster_whisper_program_url(label: str) -> Optional[str]:
    """Look up a Faster Whisper program download URL by label (e.g. 'CPU')."""
    for prog in FASTER_WHISPER_PROGRAMS:
        if prog["label"] == label or prog["value"] == label:
            return prog["url"]
    return None


def get_faster_whisper_model_repo(value: str) -> Optional[str]:
    """Look up a Faster Whisper model's ModelScope repo id by config value."""
    for model in FASTER_WHISPER_MODELS:
        if model["value"] == value:
            return model["modelscope"]
    return None
