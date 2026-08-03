"""人声/背景分离(基于 sherpa-onnx UVR 模型)。"""

from .vocal_separator import separate_vocals

__all__ = ["separate_vocals"]
