"""模型下载 URL 表(移植自 pyVideoTrans ``configure/contants.py``)。

集中维护各模型的双源下载地址(ModelScope + HuggingFace/hf-mirror),供
``core/utils/model_downloader.py`` 与各功能模块按需下载使用。当前覆盖
人声/背景分离(UVR)和说话人识别模型。

URL 前缀约定:
- ``UVR_URL_MS``:ModelScope 前缀,附带 ``{}`` 占位符,填入模型文件名。
- ``UVR_URL_HF``:HuggingFace 前缀,附带 ``{}`` 占位符,填入模型文件名。
- ``DIARIZATION_URL_MS`` / ``DIARIZATION_URL_HF``:说话人识别模型,同上占位符
  (与 pyVideoTrans ``contants.py`` 内置说话人下载地址一致)。
"""

from typing import Optional

# 人声/背景分离(UVR)模型双源 URL 前缀,``{}`` 处填入模型文件名(如
# ``UVR-MDX-NET-Inst_HQ_4.onnx``)。
UVR_URL_MS = "https://www.modelscope.cn/models/himyworld/videotrans/resolve/master/onnx/{}"
UVR_URL_HF = "https://huggingface.co/mortimerme/repocollect/resolve/main/onnx/{}?download=true"

# 默认人声分离模型(不含扩展名)。
UVR_DEFAULT_MODEL = "UVR-MDX-NET-Inst_HQ_4"

# 模型名(不含扩展名)-> 模型文件名。sherpa-onnx 的 UVR 配置接收完整 .onnx 路径。
UVR_MODEL_FILES: dict[str, str] = {
    "UVR-MDX-NET-Inst_HQ_4": "UVR-MDX-NET-Inst_HQ_4.onnx",
}

# 说话人识别(内置 sherpa-onnx 方案)模型双源 URL 前缀,``{}`` 处填入模型文件名
# (segmentation + 中/英文 embedding,straight from pyVideoTrans ''contants.py:149-159'')。
DIARIZATION_URL_MS = "https://www.modelscope.cn/models/himyworld/videotrans/resolve/master/onnx/{}"
DIARIZATION_URL_HF = "https://huggingface.co/mortimerme/repocollect/resolve/main/onnx/{}?download=true"

# 说话人识别模型 -> 文件名(sherpa-onnx ``OfflineSpeakerSegmentationPyannoteModelConfig``
# 要求完整 .onnx 路径)。embedding 依语言选择:zh 用 3dspeaker eres2net,en 用 nemo
# titanet,其他语言用跨语种 SimAMResNet34。
DIARIZATION_MODEL_FILES: dict[str, str] = {
    "segmentation": "seg_model.onnx",
    "embedding_zh": "3dspeaker_speech_eres2net_large_sv_zh-cn_3dspeaker_16k.onnx",
    "embedding_en": "nemo_en_titanet_small.onnx",
    "embedding_multi": "tidyvoicex_samresnet34.onnx",
}

DIARIZATION_MULTILINGUAL_MODEL_SIZE = 100_917_737
DIARIZATION_MULTILINGUAL_MODEL_URL = (
    "https://huggingface.co/hr16/tidyvoicex-samresnet34-onnx/resolve/main/"
    "tidyvoicex_samresnet34.onnx?download=true"
)


def uvr_model_filename(model_name: str) -> str:
    """返回模型 ``model_name`` 对应的 .onnx 文件名。

    未在 ``UVR_MODEL_FILES`` 中登记时,直接补上 ``.onnx`` 扩展名返回。
    """
    if model_name in UVR_MODEL_FILES:
        return UVR_MODEL_FILES[model_name]
    return model_name if model_name.endswith(".onnx") else f"{model_name}.onnx"


def uvr_model_urls(model_name: str) -> list[str]:
    """返回模型 ``model_name`` 的双源下载 URL 列表([ModelScope, HuggingFace])。

    顺序即尝试顺序:ModelScope 优先,失败时由调用方回退 HuggingFace。
    """
    filename = uvr_model_filename(model_name)
    return [UVR_URL_MS.format(filename), UVR_URL_HF.format(filename)]


def get_uvr_model_url(model_name: str, source: str = "ms") -> Optional[str]:
    """按来源取单个下载 URL。

    Args:
        model_name: 模型名(不含扩展名,如 ``UVR-MDX-NET-Inst_HQ_4``)。
        source: ``"ms"``(ModelScope)或 ``"hf"``(HuggingFace);其他值返回 None。

    Returns:
        对应的下载 URL;来源未知时返回 None。
    """
    urls = uvr_model_urls(model_name)
    if source == "ms":
        return urls[0]
    if source == "hf":
        return urls[1]
    return None


def diarization_model_filename(model_key: str) -> str:
    """返回说话人识别模型 ``model_key`` 对应的 .onnx 文件名。

    合法 key 由 ``DIARIZATION_MODEL_FILES`` 定义。
    """
    if model_key in DIARIZATION_MODEL_FILES:
        return DIARIZATION_MODEL_FILES[model_key]
    raise KeyError(
        f"未知说话人识别模型 key: {model_key!r},可选: {sorted(DIARIZATION_MODEL_FILES)}"
    )


def diarization_model_urls(model_key: str) -> list[str]:
    """返回说话人识别模型 ``model_key`` 的下载 URL 列表。

    中英文模型使用现有双源；多语种模型使用已验证可达的 HuggingFace 文件，下载器
    会自动回退 hf-mirror。
    """
    filename = diarization_model_filename(model_key)
    if model_key == "embedding_multi":
        return [DIARIZATION_MULTILINGUAL_MODEL_URL]
    return [
        DIARIZATION_URL_MS.format(filename),
        DIARIZATION_URL_HF.format(filename),
    ]
