"""Gradio-based local TTS base (ported from pyvideotrans ``tts/_gradio.py``).

Local TTS engines (Dots-TTS, VoxCPM) run as a local Gradio service. This base
class manages the ``gradio_client`` connection (thread-local, keyed by URL),
checks the service is reachable (with optional auto-start via a script), and
converts the returned audio to the requested output path.

Voice cloning is mandatory for these engines: each segment must carry a
reference audio (``clone_audio_path``) and its transcript
(``clone_audio_text``), which the Gradio service uses for zero-shot cloning.
"""

import subprocess
import threading
import time
from abc import abstractmethod
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from videocaptioner.core.tts.base import BaseTTS
from videocaptioner.core.tts.tts_data import TTSConfig, TTSDataSeg
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("tts.gradio")

try:  # gradio_client is an optional dependency for local TTS engines
    from gradio_client import Client as GradioClient
    from gradio_client import handle_file as _gradio_handle_file
except ImportError:  # pragma: no cover - exercised only without the SDK installed
    GradioClient = None
    _gradio_handle_file = None

# Thread-local gradio clients, keyed by service URL. Each worker thread gets
# its own client so concurrent synthesis doesn't share a connection.
_thread_local = threading.local()


class GradioBaseTTS(BaseTTS):
    """Base class for local Gradio-service TTS engines with voice cloning."""

    service_name: str = ""
    default_api_url: str = ""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        if not self.service_name:
            raise TypeError("GradioBaseTTS subclasses must set a service_name")
        api_url = (config.base_url or self.default_api_url or "").strip().rstrip("/")
        if not api_url:
            raise ValueError(f"{self.service_name} service URL (base_url) is required")
        self.api_url = api_url if api_url.startswith("http") else f"http://{api_url}"

    # -- service readiness -------------------------------------------------
    def _is_service_ready(self) -> bool:
        """Best-effort liveness probe of the Gradio service URL."""
        try:
            with urlopen(self.api_url, timeout=3) as response:
                return 200 <= response.status < 500
        except (OSError, URLError, ValueError):
            return False

    def _ensure_service_ready(self, start_script: str = "", timeout: int = 180) -> None:
        """Ensure the local service is reachable, optionally starting it first.

        If a ``start_script`` is configured and the service is down, it is
        launched (PowerShell) and polled until ready or ``timeout`` seconds
        elapse. With no script, a downed service raises a clear error.
        """
        if self._is_service_ready():
            return
        if not start_script or not Path(start_script).is_file():
            raise RuntimeError(
                f"{self.service_name} service is not reachable at {self.api_url}. "
                f"Start it manually, or configure a start_script."
            )
        logger.info("Starting %s service via %s", self.service_name, start_script)
        try:
            subprocess.Popen(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(start_script)],
                cwd=str(Path(start_script).parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to start {self.service_name} service: {exc}") from exc
        deadline = time.time() + max(1, timeout)
        while time.time() < deadline:
            if self._is_service_ready():
                logger.info("%s service is ready", self.service_name)
                return
            time.sleep(2)
        raise RuntimeError(
            f"{self.service_name} service did not become ready within {timeout}s "
            f"(checked {self.api_url})"
        )

    # -- gradio client -----------------------------------------------------
    def _get_client(self):
        if GradioClient is None:
            raise ImportError(
                "The 'gradio_client' package is required for local Gradio TTS. "
                "Install it with `pip install gradio_client`."
            )
        clients = getattr(_thread_local, "clients", None)
        if clients is None:
            clients = {}
            _thread_local.clients = clients
        client = clients.get(self.api_url)
        if client is None:
            client = GradioClient(self.api_url, httpx_kwargs={"timeout": 3600})
            clients[self.api_url] = client
        return client

    @staticmethod
    def _handle_file(path: str):
        """Wrap a local file path for gradio_client upload."""
        if _gradio_handle_file is None:
            raise ImportError(
                "The 'gradio_client' package is required for local Gradio TTS. "
                "Install it with `pip install gradio_client`."
            )
        return _gradio_handle_file(path)

    # -- voice cloning reference ------------------------------------------
    def _resolve_ref(self, segment: TTSDataSeg) -> tuple[str, str]:
        """Return ``(reference_audio_path, reference_text)`` for voice cloning.

        These engines clone the voice from a reference audio; both the audio
        and its transcript must be supplied on the segment.
        """
        ref_audio = segment.clone_audio_path
        ref_text = (segment.clone_audio_text or "").strip()
        if not ref_audio or not Path(ref_audio).is_file():
            raise ValueError(
                f"{self.service_name} requires a reference audio for voice cloning "
                f"(set clone_audio_path). Not found: {ref_audio!r}"
            )
        return ref_audio, ref_text

    # -- synthesis ---------------------------------------------------------
    @abstractmethod
    def _build_predict_kwargs(self, segment: TTSDataSeg) -> dict:
        """Build the gradio_client ``predict`` kwargs for one segment."""
        raise NotImplementedError

    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        self._ensure_service_ready(
            start_script=self.config.start_script,
            timeout=self.config.service_start_timeout,
        )
        kwargs = self._build_predict_kwargs(segment)
        client = self._get_client()
        logger.debug("%s predict kwargs: %s", self.service_name, kwargs)
        result = client.predict(**kwargs)
        src_path = self._extract_wav_path(result)
        self._convert_audio(src_path, output_path)
        segment.audio_path = output_path
        if segment.clone_audio_path:
            segment.voice = segment.voice or "clone"

    @staticmethod
    def _extract_wav_path(result) -> str:
        """Pull a file path out of the various gradio predict return shapes."""
        wav_file = result[0] if isinstance(result, (list, tuple)) and result else result
        if isinstance(wav_file, dict) and "value" in wav_file:
            wav_file = wav_file["value"]
        if not isinstance(wav_file, str):
            raise RuntimeError(f"{result!r}: gradio service returned no file path")
        return wav_file

    @staticmethod
    def _convert_audio(src_path: str, output_path: str) -> None:
        """Convert the gradio-returned audio to ``output_path`` (any common format)."""
        from pydub import AudioSegment

        audio = AudioSegment.from_file(src_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fmt = Path(output_path).suffix.lower().lstrip(".") or "wav"
        audio.export(output_path, format=fmt)
