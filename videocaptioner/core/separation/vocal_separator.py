"""人声/背景分离(port of pyVideoTrans ``process/_audio_separate.py``)。

基于 sherpa-onnx 的 ``OfflineSourceSeparation`` + UVR-MDX-NET 模型,把一段音频
(人声+伴奏)分离成独立的人声轨 ``vocal`` 与背景伴奏轨 ``instrument``。

模型按需下载:若本地 ``MODEL_PATH`` 下没有对应 ``.onnx``,会先经
:class:`ModelDownloader` 从 ModelScope / HuggingFace(hf-mirror 回退)下载到
``MODEL_PATH/separate`` 子目录。sherpa-onnx 在函数内延迟导入,保证未安装该
依赖时模块导入与项目其余功能不受影响。

注意:与 pyVideoTrans 一致,sherpa-onnx 返回的 stems 顺序为
``[0]=non_vocals(背景), [1]=vocals(人声)``,见
``_audio_separate.py:59-60``。
"""

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.model_downloader import ModelDownloader
from videocaptioner.core.utils.model_urls import (
    UVR_DEFAULT_MODEL,
    uvr_model_filename,
    uvr_model_urls,
)

logger = setup_logger("separation")

# On Windows, suppress "Application Error" crash dialogs for ffmpeg.
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# sherpa-onnx 的 UVR 模型期望的输入采样率与声道数(与 pyVideoTrans
# ``_stage_prepare.py`` 预处理一致)。
_MODEL_SAMPLE_RATE = 44100
_MODEL_CHANNELS = 2

# 模型文件存放的 MODEL_PATH 子目录。
_MODEL_SUBDIR = "separate"


def _model_package_dir() -> Path:
    """返回模型下载/存放目录(``MODEL_PATH/separate``)。"""
    return Path(MODEL_PATH) / _MODEL_SUBDIR


def _ensure_model(model_name: str, progress: Optional[Callable[[int, str], None]]) -> Path:
    """确保 UVR 模型 ``.onnx`` 已存在,缺失则下载。

    返回模型文件完整路径。下载失败时抛出带手动放置说明的 ``RuntimeError``。

    Args:
        model_name: 模型名(不含扩展名,如 ``UVR-MDX-NET-Inst_HQ_4``)。
        progress: 可选的 ``(percent, message)`` 进度回调(percent 为 int 0-100)。
    """
    filename = uvr_model_filename(model_name)
    target_dir = _model_package_dir()
    model_path = target_dir / filename
    if model_path.is_file() and model_path.stat().st_size > 0:
        return model_path

    downloader = ModelDownloader(target_dir)
    cb = progress or (lambda _p, _s: None)
    last_error: Optional[Exception] = None
    for url in uvr_model_urls(model_name):
        try:
            cb(0, f"正在下载人声分离模型 {model_name} ...")
            # ModelDownloader 对 huggingface.co URL 会自动回退 hf-mirror。
            downloader.download(url, filename=filename)
            if model_path.is_file() and model_path.stat().st_size > 0:
                cb(100, f"人声分离模型下载完成:{filename}")
                return model_path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("下载人声分离模型 %s 失败: %s", filename, exc)
            model_path.unlink(missing_ok=True)

    raise RuntimeError(
        f"人声分离模型 {filename} 下载失败: {last_error}\n"
        f"请手动下载以下任一链接并放置到目录:\n  {target_dir}\n"
        f"  - {uvr_model_urls(model_name)[0]}\n"
        f"  - {uvr_model_urls(model_name)[1]}\n"
        f"文件名需为 {filename}"
    )


def _preprocess_wav(audio_path: str, work_dir: Path) -> Path:
    """把输入音频转成模型要求的 44100Hz 立体声 wav。

    输入本就是 44100Hz / 2 声道 wav 时直接返回原路径,否则用 ffmpeg 转码。
    sherpa-onnx 的 UVR 分离不接受非 wav / 采样率不符的输入,与 pyVideoTrans
    ``_stage_prepare.py`` 的预处理(44100 Hz, 2ch, pcm_s16le)一致。

    Args:
        audio_path: 输入音频路径。
        work_dir: 中间产物目录。

    Returns:
        满足模型输入要求的 wav 路径。
    """
    src = Path(audio_path)
    if src.suffix.lower() == ".wav":
        # 仅当确认已是 44100Hz / 2 声道时才放行;无法确认一律转码。
        try:
            import soundfile as sf

            info = sf.info(str(src))
            if info.samplerate == _MODEL_SAMPLE_RATE and info.channels == _MODEL_CHANNELS:
                return src
        except Exception:
            pass
    out = work_dir / "separate_input.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        str(_MODEL_CHANNELS),
        "-ar",
        str(_MODEL_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)
    return out


def separate_vocals(
    audio_path: str,
    work_dir: str,
    model_name: str = UVR_DEFAULT_MODEL,
    progress: Optional[Callable[[int, str], None]] = None,
) -> Tuple[str, str]:
    """把 ``audio_path`` 分离成 (人声, 背景伴奏) 两条 wav 轨。

    严格对照 pyVideoTrans ``process/_audio_separate.py`` 的 sherpa-onnx 调用
    方式移植。输入非 wav 或采样率不符时先用 ffmpeg 转成 44100Hz 立体声 wav;
    模型缺失时经 :class:`ModelDownloader` 下载到 ``MODEL_PATH/separate``。

    Args:
        audio_path: 输入音频(视频/音频文件)路径。
        work_dir: 中间产物(重采样 wav、分离结果)目录。
        model_name: UVR 模型名(不含扩展名)。
        progress: 可选的 ``(percent, message)`` 进度回调(percent 为 int 0-100)。

    Returns:
        ``(vocal_path, instrument_path)`` 二元组,分别指向人声与背景伴奏 wav。

    Raises:
        RuntimeError: 模型下载失败或 sherpa-onnx 未安装。
        subprocess.CalledProcessError: ffmpeg 预处理失败。
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    cb = progress or (lambda _p, _s: None)

    # 1) 确保模型存在(缺失则下载)。
    model_path = _ensure_model(model_name, cb)

    # 2) 预处理:转成模型要求的 44100Hz 立体声 wav。
    cb(2, "预处理音频...")
    input_wav = _preprocess_wav(audio_path, work)

    # 3) 延迟导入 sherpa-onnx(未安装时给出清晰错误,不影响其余功能)。
    try:
        import numpy as np
        import sherpa_onnx
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "人声分离需要 sherpa-onnx / numpy / soundfile。请先安装:"
            "`uv sync` 或 `pip install sherpa-onnx numpy soundfile`"
        ) from exc

    # 4) 构造离线分离器(严格照 pyVideoTrans _audio_separate.py:17-36)。
    separation_config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            uvr=sherpa_onnx.OfflineSourceSeparationUvrModelConfig(
                model=str(model_path),
            ),
            num_threads=4,
            debug=False,
            provider="cpu",
        )
    )
    if not separation_config.validate():
        raise RuntimeError("人声分离配置校验失败,请检查模型文件。")
    separator = sherpa_onnx.OfflineSourceSeparation(separation_config)

    # 5) 读取音频并分离。
    cb(5, "正在分离人声与背景声(可能需要几分钟)...")
    samples, sample_rate = sf.read(str(input_wav), dtype="float32", always_2d=True)
    samples = np.transpose(samples)
    if samples.shape[1] <= samples.shape[0]:
        raise RuntimeError(
            f"音频通道数异常(应为 (num_channels, num_samples)),实际 {samples.shape}"
        )
    samples = np.ascontiguousarray(samples)
    output = separator.process(sample_rate=sample_rate, samples=samples)

    # sticks 顺序:[0]=non_vocals(背景), [1]=vocals(人声)。
    non_vocals = np.transpose(output.stems[0].data)
    vocals = np.transpose(output.stems[1].data)

    vocal_path = work / "vocal.wav"
    instrument_path = work / "instrument.wav"
    sf.write(str(vocal_path), vocals, samplerate=output.sample_rate)
    sf.write(str(instrument_path), non_vocals, samplerate=output.sample_rate)

    cb(100, "人声与背景声分离完成")
    return str(vocal_path), str(instrument_path)
