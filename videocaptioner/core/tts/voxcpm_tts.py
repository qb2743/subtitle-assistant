"""VoxCPM local Gradio engine (zero-shot voice cloning).

Ports the v2 parameter shape from ``pyvideotrans/tts/_voxcpm.py``. The engine
calls the local Gradio service's ``/generate`` endpoint with the target text
plus a reference audio (``clone_audio_path``) and its transcript
(``clone_audio_text``) for voice cloning.
"""

from videocaptioner.core.tts.gradio_base import GradioBaseTTS
from videocaptioner.core.tts.tts_data import TTSDataSeg


class VoxCPMTTS(GradioBaseTTS):
    """VoxCPM v2 engine backed by a local Gradio service."""

    service_name = "voxcpmtts"
    default_api_url = "http://127.0.0.1:9880"

    def _build_predict_kwargs(self, segment: TTSDataSeg) -> dict:
        ref_audio, ref_text = self._resolve_ref(segment)
        version = (self.config.voxcpm_version or "v2").strip().lower()
        kwargs = {
            "do_normalize": True,
            "denoise": True,
            "control_instruction": "",
            "api_name": "/generate",
        }
        if version == "v1":
            kwargs.update(
                {
                    "text_input": segment.text.strip(),
                    "prompt_wav_path_input": self._handle_file(ref_audio),
                    "inference_timesteps_input": 10,
                    "cfg_value_input": 2,
                    "prompt_text_input": ref_text,
                }
            )
        elif version == "hf":
            kwargs.update(
                {
                    "text_input": segment.text.strip(),
                    "use_prompt_text": bool(ref_text),
                    "reference_wav_path_input": self._handle_file(ref_audio),
                    "cfg_value_input": 2,
                    "prompt_text_input": ref_text,
                }
            )
        else:
            kwargs.update(
                {
                    "text": segment.text.strip(),
                    "use_prompt_text": bool(ref_text),
                    "ref_wav": self._handle_file(ref_audio),
                    "dit_steps": 10,
                    "cfg_value": 2,
                    "prompt_text_value": ref_text,
                }
            )
        return kwargs
