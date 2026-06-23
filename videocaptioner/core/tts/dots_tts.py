"""Dots-TTS local Gradio engine (zero-shot voice cloning).

Ports the parameter shape from ``pyvideotrans/tts/_dotstts.py``. The engine
calls the local Gradio service's ``/run_synthesis`` endpoint with the target
text plus a reference audio (``clone_audio_path``) and its transcript
(``clone_audio_text``) for voice cloning.
"""

from videocaptioner.core.tts.gradio_base import GradioBaseTTS
from videocaptioner.core.tts.tts_data import TTSDataSeg


class DotsTTS(GradioBaseTTS):
    """Dots-TTS engine backed by a local Gradio service."""

    service_name = "dotstts"
    default_api_url = "http://127.0.0.1:7860"

    def _build_predict_kwargs(self, segment: TTSDataSeg) -> dict:
        ref_audio, ref_text = self._resolve_ref(segment)
        return {
            "text": segment.text.strip(),
            "prompt_audio_path": self._handle_file(ref_audio),
            "prompt_text": ref_text,
            "num_steps": 10,
            "guidance_scale": 1.2,
            "normalize_text": False,
            "seed": 0,
            "api_name": "/run_synthesis",
        }
