"""说话人识别与字幕分配(port of pyVideoTrans ``process/_audio_speakers.py``)。

- ``speaker_diarizer.diarize``: sherpa-onnx 内置方案(segmentation + embedding +
  FastClustering)对一段音频做说话人分离,返回无序的说话人区间列表。
- ``assign.assign_speakers``: 扫描线分配,把说话人区间贴到字幕行上,得到与
  :class:`DubbingSegment` 平行的 ``"spk0"/""`` 数组,并支持 sidecar JSON
  (仿 pyVideoTrans ``speaker.json``)。

模型缺失时经 :class:`ModelDownloader` 下载到 ``MODEL_PATH/diarization``。
"""

from .assign import (
    assign_speakers,
    read_speaker_json,
    remap_speakers_ms,
    speaker_sidecar_path,
    write_speaker_json,
)
from .speaker_diarizer import diarize

__all__ = [
    "diarize",
    "assign_speakers",
    "write_speaker_json",
    "read_speaker_json",
    "remap_speakers_ms",
    "speaker_sidecar_path",
]
