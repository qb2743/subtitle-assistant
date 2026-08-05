"""说话人识别(port of pyVideoTrans ``built_speakers`` 内置方案)。

基于 sherpa-onnx 的 ``OfflineSpeakerDiarization``(segmentation +
 3dspeaker eres2net(zh)/ nemo titanet(en)/ SimAMResNet34(multilingual)
 embedding + FastClustering),
对一段音频做说话人分离,返回无序的说话人区间列表。

pyVideoTrans 参照点:``videotrans/process/_audio_speakers.py:287-375``
(``built_speakers``)与 ``:298-327``(``init_speaker_diarization``)。

模型按需下载:若本地 ``MODEL_PATH/diarization`` 下没有对应 ``.onnx``,会先经
:class:`ModelDownloader` 从 ModelScope / HuggingFace(hf-mirror 回退)下载。
sherpa-onnx 在函数内延迟导入,保证未安装该依赖时模块导入与项目其余功能不受影响。

音频重采样不走 librosa(避免引入重依赖),而是复用 ffmpeg 转成模型期望的采样率/
声道(与 ``core/separation/vocal_separator.py`` 一致)。
"""

import json
import multiprocessing
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.core.utils.model_downloader import ModelDownloader
from videocaptioner.core.utils.model_urls import (
    diarization_model_filename,
    diarization_model_urls,
)

logger = setup_logger("diarization")

# On Windows, suppress "Application Error" crash dialogs for ffmpeg.
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# 模型文件存放的 MODEL_PATH 子目录。
_MODEL_SUBDIR = "diarization"

# 内置模型默认语言(仅支持 zh/en)。
_DEFAULT_LANGUAGE = "zh"


def _model_package_dir() -> Path:
    """返回模型下载/存放目录(``MODEL_PATH/diarization``)。"""
    return Path(MODEL_PATH) / _MODEL_SUBDIR


def _ensure_model(model_key: str, progress: Optional[Callable[[int, str], None]]) -> Path:
    """确保说话人识别模型 ``.onnx`` 已存在,缺失则下载。

    返回模型文件完整路径。下载失败时抛出带手动放置说明的 ``RuntimeError``。

    Args:
        model_key: ``model_urls.DIARIZATION_MODEL_FILES`` 中的模型 key。
        progress: 可选的 ``(percent, message)`` 进度回调(percent 为 int 0-100)。
    """
    filename = diarization_model_filename(model_key)
    target_dir = _model_package_dir()
    model_path = target_dir / filename
    if model_path.is_file() and model_path.stat().st_size > 0:
        return model_path

    downloader = ModelDownloader(target_dir)
    cb = progress or (lambda _p, _s: None)
    last_error: Optional[Exception] = None
    for url in diarization_model_urls(model_key):
        try:
            cb(0, f"正在下载说话人识别模型 {filename} ...")
            # ModelDownloader 对 huggingface.co URL 会自动回退 hf-mirror。
            downloader.download(url, filename=filename)
            if model_path.is_file() and model_path.stat().st_size > 0:
                cb(100, f"说话人识别模型下载完成:{filename}")
                return model_path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("下载说话人识别模型 %s 失败: %s", filename, exc)
            model_path.unlink(missing_ok=True)

    raise RuntimeError(
        f"说话人识别模型 {filename} 下载失败: {last_error}\n"
        f"请手动下载以下任一链接并放置到目录:\n  {target_dir}\n"
        f"  - {diarization_model_urls(model_key)[0]}\n"
        f"  - {diarization_model_urls(model_key)[1]}\n"
        f"文件名需为 {filename}"
    )


def _ensure_models(
    language: str, progress: Optional[Callable[[int, str], None]]
) -> tuple[Path, Path]:
    """确保说话人识别所需的 segmentation + embedding 两个模型都存在。

    Args:
        language: ``"zh"`` / ``"en"`` / 其他,决定选用中文、英文或多语种 embedding。
        progress: 进度回调。

    Returns:
        ``(segmentation_path, embedding_path)``。
    """
    seg_path = _ensure_model("segmentation", progress)
    emb_key = {
        "zh": "embedding_zh",
        "en": "embedding_en",
    }.get(language, "embedding_multi")
    emb_path = _ensure_model(emb_key, progress)
    return seg_path, emb_path


def _load_audio_mono(audio_path: str, target_sr: int):
    """用 ffmpeg 把 ``audio_path`` 转成单声道 ``target_sr`` 采样率的 float32 数组。

    返回 ``(samples, sample_rate)``,其中 ``samples`` 为 1D float32 numpy 数组
    (sherpa-onnx ``OfflineSpeakerDiarization.process`` 期望的格式)。
    """
    import soundfile as sf

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-c:a",
            "pcm_s16le",
            str(tmp.name),
        ]
        subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)
        audio, sr = sf.read(tmp.name, dtype="float32", always_2d=True)
        return audio[:, 0], sr
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _init_speaker_diarization(seg_path: Path, emb_path: Path, num_speakers: int):
    """构造 sherpa-onnx ``OfflineSpeakerDiarization``(严格照 pyVideoTrans 调用方式)。

    pyVideoTrans 参照点:``_audio_speakers.py:298-327``。

    Args:
        seg_path: segmentation 模型 .onnx 路径。
        emb_path: embedding 模型 .onnx 路径。
        num_speakers: 说话人数量语义:<0 不启用 / 0 不限 / >0 上限。
    """
    import sherpa_onnx

    _cf = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=_native_model_path(seg_path)
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_native_model_path(emb_path)
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers, threshold=0.5
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not _cf.validate():
        raise RuntimeError(
            "说话人识别配置校验失败,请检查模型文件是否完整。"
        )
    return sherpa_onnx.OfflineSpeakerDiarization(_cf)


def _native_model_path(model_path: Path) -> str:
    """Return an ASCII path for Windows libraries that cannot open Unicode paths."""
    resolved = model_path.resolve()
    if sys.platform != "win32" or str(resolved).isascii():
        return str(resolved)

    try:
        relative = resolved.relative_to(Path.cwd().resolve())
    except ValueError:
        relative = None
    if relative is not None and str(relative).isascii():
        return str(relative)

    cache_dir = Path(tempfile.gettempdir()) / "videocaptioner-models" / "diarization"
    if not str(cache_dir).isascii():
        raise RuntimeError("说话人识别模型路径必须位于不含中文的目录")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / resolved.name
    source_stat = resolved.stat()
    if (
        not cached.is_file()
        or cached.stat().st_size != source_stat.st_size
        or cached.stat().st_mtime_ns != source_stat.st_mtime_ns
    ):
        shutil.copy2(resolved, cached)
    return str(cached)


def _normalize_diarizations(raw_output: List[dict]) -> List[dict]:
    """把 sherpa-onnx 原始区间标准化为 ``{"start","end","speaker"}`` 且 speaker 重映射。

    保持 pyVideoTrans ``_normalize_diarizations``(``_audio_speakers.py:89``)语义:
    把原始说话人 id 按首次出现顺序映射为 ``spk0``, ``spk1``, ...;start/end 保持秒。
    """
    speaker_list = sorted({item["speaker"] for item in raw_output})
    spk_map = {spk: f"spk{i}" for i, spk in enumerate(speaker_list)}
    output = []
    for item in raw_output:
        output.append(
            {
                "start": item["start"],
                "end": item["end"],
                "speaker": spk_map.get(item["speaker"], "spk0"),
            }
        )
    return output


def _diarize_worker(
    audio_path: str,
    num_speakers: int,
    language: str,
    result_path: str,
) -> None:
    try:
        result = diarize(
            audio_path,
            num_speakers=num_speakers,
            language=language,
            isolate_process=False,
        )
        payload = {"result": result, "error": ""}
    except Exception as exc:  # noqa: BLE001
        logger.exception("说话人识别子进程失败: %s", exc)
        payload = {"result": [], "error": str(exc)}
    Path(result_path).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _diarize_in_subprocess(
    audio_path: str,
    num_speakers: int,
    language: str,
    cancelled: Optional[Callable[[], bool]] = None,
) -> List[dict]:
    result_file = tempfile.NamedTemporaryFile(
        suffix=".json", prefix="videocaptioner-diarization-", delete=False
    )
    result_file.close()
    result_path = Path(result_file.name)
    process = multiprocessing.get_context("spawn").Process(
        target=_diarize_worker,
        args=(audio_path, num_speakers, language, str(result_path)),
    )
    process.daemon = True
    try:
        process.start()
        if hasattr(process, "is_alive"):
            while process.is_alive():
                process.join(0.2)
                if cancelled and cancelled():
                    process.terminate()
                    process.join(5)
                    raise RuntimeError("任务已取消")
        else:
            process.join()
        if process.exitcode != 0:
            raise RuntimeError(f"说话人识别子进程异常退出: {process.exitcode}")
        payload = json.loads(result_path.read_text(encoding="utf-8") or "{}")
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result") or []
    finally:
        process.close()
        result_path.unlink(missing_ok=True)


def diarize(
    audio_path: str,
    num_speakers: int = 0,
    language: str = _DEFAULT_LANGUAGE,
    progress: Optional[Callable[[int, str], None]] = None,
    isolate_process: bool = False,
    cancelled: Optional[Callable[[], bool]] = None,
) -> List[dict]:
    """对 ``audio_path`` 做说话人分离,返回无序说话人区间列表。

    严格对照 pyVideoTrans ``built_speakers``(``_audio_speakers.py:287-375``)的
    sherpa-onnx 调用方式移植。输入任意音频/视频文件,经 ffmpeg 重采样为模型期望的
    单声道采样率;模型缺失时经 :class:`ModelDownloader` 下载到 ``MODEL_PATH/diarization``。

    Args:
        audio_path: 输入音频(或视频)路径。
        num_speakers: 说话人数量语义:<0 不启用 / 0 不限(自动聚类)/ >0 上限。
        language: 模型语言,``"zh"`` / ``"en"`` / ``"multi"``;其他值使用多语种模型。
        progress: 可选的 ``(percent, message)`` 进度回调(percent 为 int 0-100)。
        isolate_process: Windows GUI 中隔离原生推理，避免 sherpa-onnx 阻塞事件循环。
        cancelled: 可选取消检查，返回 True 时终止隔离推理进程。

    Returns:
        元素形如 ``{"start": 秒(float), "end": 秒(float), "speaker": "spk0"}`` 的列表,
        按开始时间升序。

    Raises:
        RuntimeError: 模型下载失败或 sherpa-onnx / soundfile 未安装。
        subprocess.CalledProcessError: ffmpeg 预处理失败。
    """
    cb = progress or (lambda _p, _s: None)

    # 1) 确保模型存在(缺失则下载)。
    seg_path, emb_path = _ensure_models(language, cb)

    if isolate_process and sys.platform == "win32":
        cb(5, "正在识别说话人（界面可继续操作，可能需要几分钟）...")
        result = _diarize_in_subprocess(
            audio_path, num_speakers, language, cancelled
        )
        cb(100, f"说话人识别完成,共 {len(set(d['speaker'] for d in result))} 位说话人")
        return result

    # 2) 延迟导入 sherpa-onnx(未安装时给出清晰错误,不影响其余功能)。
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "说话人识别需要 sherpa-onnx / soundfile。请先安装:"
            "`uv sync` 或 `pip install sherpa-onnx soundfile`"
        ) from exc

    # 3) 构造离线分离器。
    sd = _init_speaker_diarization(seg_path, emb_path, num_speakers)

    # 4) 读取音频(重采样到模型期望采样率 / 单声道)。
    cb(2, "预处理音频...")
    samples, sample_rate = _load_audio_mono(audio_path, sd.sample_rate)
    if sample_rate != sd.sample_rate:
        raise RuntimeError(
            f"Expected sample rate {sd.sample_rate}, given: {sample_rate}"
        )

    # 5) 分离说话人(带进度回调)。
    def _progress_callback(num_processed_chunk: int, num_total_chunks: int) -> int:
        pct = int(num_processed_chunk / num_total_chunks * 100) if num_total_chunks > 0 else 0
        cb(pct, f"正在识别说话人 {num_processed_chunk}/{num_total_chunks}")
        return pct

    cb(5, "正在识别说话人(可能需要几分钟)...")
    result = sd.process(samples, callback=_progress_callback).sort_by_start_time()

    raw_output = [
        {"start": r.start, "end": r.end, "speaker": f"spk{r.speaker}"} for r in result
    ]
    normalized = _normalize_diarizations(raw_output)
    cb(100, f"说话人识别完成,共 {len(set(d['speaker'] for d in normalized))} 位说话人")
    return normalized
