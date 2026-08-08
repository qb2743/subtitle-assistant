"""说话人区间 → 字幕行的扫描线分配(port of pyVideoTrans ``_assign_speakers``)。

pyVideoTrans 参照点:``videotrans/process/_audio_speakers.py:18-77``(``_assign_speakers``)。
输入改毫秒(字幕行已是毫秒时间戳),说话人区间以秒为单位(来自
``speaker_diarizer.diarize`` 返回值)在函数内转毫秒。输出为与字幕行平行的
``"spk0"/""`` 数组:与任一说话人区间重叠足够多(见下)的记为对应 ``spk``,
否则为 ``""``(未标注)。

分配规则(保持 pyVideoTrans 语义,仅把默认占位值由 ``"spk0"`` 改为 ``""``:
pyVideoTrans 用 ``"spk0"`` 兼作"未知",而本项目的解说员过滤依赖空串识别未标注行):
- 与多个说话人区间重叠 → 取累计重叠时长最长的说话人;
- 只与一个说话人区间重叠 → 要求重叠时长 > 0.2 * 字幕时长才标注,否则标 ``""``;
- 无重叠 → ``""``。
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

__all__ = [
    "assign_speakers",
    "write_speaker_json",
    "read_speaker_json",
    "assign_speakers_ms",
    "remap_speakers_ms",
    "speaker_sidecar_path",
]


def assign_speakers_ms(
    subtitles: List[tuple[int, int]],
    diarizations: List[tuple[tuple[int, int], str]],
) -> List[str]:
    """核心扫描线分配(纯毫秒,方便单测)。

    Args:
        subtitles: [(start_ms, end_ms), ...],保持原字幕顺序。
        diarizations: [((start_ms, end_ms), speaker_id), ...],无序,内部会按开始时间排序。

    Returns:
        与 ``subtitles`` 平行(同下标)的 ``"spk0"/""`` 数组。
    """
    # ----------------- 1. 预处理 diarizations -----------------
    clean_diars: List[tuple[int, int, str]] = []
    for dia in diarizations:
        if len(dia) == 2 and len(dia[0]) == 2 and dia[0][0] < dia[0][1]:
            clean_diars.append((dia[0][0], dia[0][1], dia[1]))
    clean_diars.sort(key=lambda x: x[0])  # 按开始时间排序

    # ----------------- 2. 预处理 subtitles(保留原顺序) -----------------
    indexed_subs: List[tuple[int, Optional[int], Optional[int]]] = []
    for idx, sub in enumerate(subtitles):
        if len(sub) == 2 and sub[0] < sub[1]:
            indexed_subs.append((idx, sub[0], sub[1]))
        else:
            indexed_subs.append((idx, None, None))

    valid_subs = [s for s in indexed_subs if s[1] is not None]
    valid_subs.sort(key=lambda x: x[1])  # 只对有效片段按开始时间排序

    # 输出数组,默认全是 ""(未标注说话人)。
    output: List[str] = [""] * len(subtitles)

    # ----------------- 3. 扫描线分配说话人 -----------------
    d_ptr = 0
    active: List[tuple[int, int, str]] = []  # 存储 (d_start, d_end, speaker)
    total_diars = len(clean_diars)

    for orig_idx, s_start, s_end in valid_subs:
        duration = s_end - s_start

        # 将开始时间 < 字幕结束时间 的 diar 加入窗口
        while d_ptr < total_diars and clean_diars[d_ptr][0] < s_end:
            active.append(clean_diars[d_ptr])
            d_ptr += 1

        # 移除窗口中已经结束的 diar(结束时间 <= 字幕开始时间)
        active = [d for d in active if d[1] > s_start]

        # 计算重叠
        overlaps = defaultdict(int)
        for d_start, d_end, spk in active:
            o_start = max(s_start, d_start)
            o_end = min(s_end, d_end)
            overlaps[spk] += (o_end - o_start)

        if not overlaps:
            continue  # 保持 ""

        num_speakers = len(overlaps)
        best_spk = max(overlaps, key=overlaps.get)
        max_overlap = overlaps[best_spk]

        if num_speakers > 1:
            output[orig_idx] = best_spk
        else:  # num_speakers == 1
            if max_overlap > 0.2 * duration:
                output[orig_idx] = best_spk
            # 否则保持 ""
    return output


def remap_speakers_ms(
    source_subtitles: List[tuple[int, int]],
    source_speakers: List[str],
    target_subtitles: List[tuple[int, int]],
) -> List[str]:
    """Remap line-level speaker labels to a changed subtitle timeline.

    Translation, subtitle splitting, and manual editing may change line indexes
    while retaining the underlying time ranges. Treat each labelled source row
    as a speaker interval and reuse the normal overlap assignment for the final
    rows. Blank or invalid source labels are ignored.
    """
    labelled_intervals: List[tuple[tuple[int, int], str]] = []
    for interval, raw_speaker in zip(source_subtitles, source_speakers):
        if len(interval) != 2 or interval[0] >= interval[1]:
            continue
        speaker = str(raw_speaker or "").strip()
        if not speaker:
            continue
        labelled_intervals.append(((int(interval[0]), int(interval[1])), speaker))
    return assign_speakers_ms(target_subtitles, labelled_intervals)


def speaker_sidecar_path(subtitle_path: str | Path) -> Path:
    """Return the conventional ``<subtitle-stem>.speaker.json`` sidecar path."""
    return Path(subtitle_path).with_suffix(".speaker.json")


def assign_speakers(segments: list, diarizations: List[dict]) -> List[str]:
    """把说话人区间分配到 DubbingSegment 上,返回平行 ``"spk0"/""`` 数组。

    Args:
        segments: 字幕行列表(需暴露 ``start_ms``/``end_ms``,如
            :class:`~videocaptioner.core.dubbing.models.DubbingSegment`)。
        diarizations: ``speaker_diarizer.diarize`` 的返回值,元素形如
            ``{"start": 秒, "end": 秒, "speaker": "spk0"}``。

    Returns:
        与 ``segments`` 等长、同下标的 ``"spk0"/""`` 数组。
    """
    subtitles = [(int(seg.start_ms), int(seg.end_ms)) for seg in segments]
    diar_ms = [
        ((int(round(d["start"] * 1000)), int(round(d["end"] * 1000))), d["speaker"])
        for d in diarizations
    ]
    return assign_speakers_ms(subtitles, diar_ms)


def write_speaker_json(speaker_labels: List[str], path: str | Path) -> str:
    """把平行说话人数组写成 sidecar JSON(仿 pyVideoTrans ``speaker.json``)。

    Args:
        speaker_labels: ``assign_speakers`` 的输出。
        path: 输出路径(通常为输出音频同目录的 ``<stem>.speaker.json``)。

    Returns:
        写入后的路径字符串。
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(speaker_labels, ensure_ascii=False), encoding="utf-8")
    return str(out)


def read_speaker_json(path: str | Path) -> list:
    """读取 ``write_speaker_json`` 写的 sidecar 到平行数组。

    文件缺失或内容非法返回空列表(不抛错,便于调用方安全回退)。
    """
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
