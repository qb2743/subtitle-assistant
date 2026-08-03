"""模型下载 URL 表(移植自 pyVideoTrans ``configure/contants.py``)。

集中维护各模型的双源下载地址(ModelScope + HuggingFace/hf-mirror),供
``core/utils/model_downloader.py`` 与各功能模块按需下载使用。当前仅覆盖
人声/背景分离(UVR)模型,后续说话人识别等模型可在此追加。

URL 前缀约定:
- ``UVR_URL_MS``:ModelScope 前缀,附带 ``{}`` 占位符,填入模型文件名。
- ``UVR_URL_HF``:HuggingFace 前缀,附带 ``{}`` 占位符,填入模型文件名。
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
