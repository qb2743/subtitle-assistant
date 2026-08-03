"""背景音回嵌(port of pyVideoTrans ``task/_stage_audio.py`` 的 ``_separate`` / ``_back_music``)。

把分离出的背景伴奏(或额外 BGM)与配音轨按音量混音回嵌成最终音频。ffmpeg 的
``amix`` 以 ``duration=first`` 对齐——以第一条输入(配音轨)为总时长,背景音
短于配音时(`loop=True` 用 ``-stream_loop -1`` 在输入侧循环)可补足,否则按
``duration=first`` 直接截断。

纯命令构造函数 ``build_mix_command`` 与执行函数 ``mix_background`` 分离,便于
单测命令构造与 ffmpeg 集成。
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# On Windows, suppress "Application Error" crash dialogs for ffmpeg.
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def build_mix_command(
    dubbed_audio: str,
    instrument_path: Optional[str],
    volume: float,
    loop: bool,
    extra_bgm_path: Optional[str],
    output_path: str,
) -> List[str]:
    """构造背景音回嵌的完整 ffmpeg 命令(纯函数,便于单测)。

    输入 0 为配音轨;``instrument_path`` 与 ``extra_bgm_path`` 任一存在时作为
    后续输入。背景输入(模型分离的背景音与额外 BGM 均如此)乘以 ``volume``。

    ``loop=True`` 时对每个背景输入加 ``-stream_loop -1``(输入侧无限循环),由
    ``amix=duration=first`` 以配音轨为总时长截断;``loop=False`` 则不循环,背景
    音播放一遍,短于配音时提前结束(截断)。

    Args:
        dubbed_audio: 配音轨(无背景)音频路径。
        instrument_path: 分离出的背景伴奏轨路径;可为 None。
        volume: 背景音音量(线性,如 0.8)。
        loop: 背景音短于配音时是否循环。
        extra_bgm_path: 额外背景音乐路径;可为 None。
        output_path: 混音输出路径。

    Returns:
        可直接交给 ``subprocess.run`` 的 ffmpeg argv 列表。

    Raises:
        ValueError: 未提供任何背景音(instrument 与 extra_bgm 均为 None)。
    """
    bgm_paths: List[str] = []
    if instrument_path:
        bgm_paths.append(str(instrument_path))
    if extra_bgm_path:
        bgm_paths.append(str(extra_bgm_path))
    if not bgm_paths:
        raise ValueError("mix_background 需要至少一个背景音(instrument 或 extra_bgm)")

    cmd: List[str] = ["ffmpeg", "-y", "-v", "error"]
    cmd += ["-i", str(dubbed_audio)]
    for bgm in bgm_paths:
        if loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(bgm)]

    n_inputs = len(bgm_paths) + 1
    parts: List[str] = []
    for i, _bgm in enumerate(bgm_paths, start=1):
        parts.append(f"[{i}:a]volume={volume:.3f}[a{i}]")
    mix_in = "[0:a]" + "".join(f"[a{i}]" for i in range(1, n_inputs))
    parts.append(
        f"{mix_in}amix=inputs={n_inputs}:duration=first:dropout_transition=2[a]"
    )
    cmd += ["-filter_complex", ";".join(parts)]
    cmd += [
        "-map",
        "[a]",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    return cmd


def mix_background(
    dubbed_audio: str,
    instrument_path: Optional[str] = None,
    volume: float = 0.8,
    loop: bool = True,
    extra_bgm_path: Optional[str] = None,
    output_path: str = "",
) -> str:
    """把背景音回嵌到配音轨并写出 ``output_path``。

    语义对齐 pyVideoTrans ``_stage_audio.py``:``amix=inputs=N:duration=first:
    dropout_transition=2``,以配音轨为总时长;背景音乘以 ``volume``;短于配音时
    按 ``loop`` 决定是否循环。

    Args:
        dubbed_audio: 配音轨(无背景)音频路径。
        instrument_path: 分离出的背景伴奏轨路径;可为 None。
        volume: 背景音音量(线性,如 0.8)。
        loop: 背景音短于配音时是否循环。
        extra_bgm_path: 额外背景音乐路径;可为 None。
        output_path: 混音输出路径;为空时自动取 ``dubbed_audio`` 同目录下
            ``\"{stem}_bgm.wav\"``。

    Returns:
        混音输出路径。

    Raises:
        ValueError: 未提供任何背景音。
        subprocess.CalledProcessError: ffmpeg 混音失败。
    """
    if not output_path:
        dst = Path(dubbed_audio)
        output_path = str(dst.with_name(f"{dst.stem}_bgm.wav"))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_mix_command(
        dubbed_audio,
        instrument_path,
        volume,
        loop,
        extra_bgm_path,
        output_path,
    )
    subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)
    return output_path
