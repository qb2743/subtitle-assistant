"""解说/旁白字幕过滤(port of pyVideoTrans ``process/narrator_filter.py``)。

纯算法模块:输入 ``DubbingSegment`` 列表 + 与之一一对应的说话人平行数组
(``core/diarization/assign.assign_speakers`` 的输出),输出 (保留的原始下标,
 report 字典)。不 import 任何 PySide6/Qt,不访问网络,可独立单测。

pyVideoTrans 参照点:``videotrans/process/narrator_filter.py``
- ``filter_narrator_subtitles``: ``:255-386``
- ``pick_narrator``: ``:115-194``(时长占比,min_share 默认 0.45,前两名差距 <5% 需复核)
- ``detect_text_lang``: ``:54-93``

数据模型适配:
- 字幕条目为 ``DubbingSegment``,时间戳字段 ``start_ms/end_ms`` 单位为**毫秒**;
- 说话人信息在与字幕行平行的 ``speakers`` 数组里,长度可与字幕数不等:统计时按行号
  zip 对齐截断,不一致时在 report 里记 ``warnings`` 与 ``speakers_len_mismatch=True``。
"""

from __future__ import annotations

from typing import Optional

from .models import DubbingSegment

DEFAULT_MIN_SHARE = 0.45

# normalize 后视为「无有效说话人」的占位值(不参与主说话人竞选,也不记入 speaker 统计)
_UNKNOWN_SPEAKER_IDS = frozenset({"unknown", "none", "null", "n/a", "n-a", "未识别", "未知"})


def _duration_ms(sub: DubbingSegment) -> float:
    """字幕条目的毫秒时长(end_ms - start_ms)。非法按 0 处理。"""
    try:
        start = float(getattr(sub, "start_ms", 0) or 0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(getattr(sub, "end_ms", 0) or 0)
    except (TypeError, ValueError):
        end = 0.0
    return end - start


def normalize_speaker_id(raw) -> Optional[str]:
    """规范化 speaker id:空串 / None / 仅空白 / 常见「未知」占位 → None,其余 strip 后返回。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.lower() in _UNKNOWN_SPEAKER_IDS:
        return None
    return text


def detect_text_lang(text) -> str:
    """轻量语种判断(无外部模型)。

    返回: 'zh' | 'en' | 'mixed' | 'other' | 'empty'
    用于「中文解说 + 英文原片」等场景,补救 diarization 把同语解说误标成其它 speaker。
    CJK 范围:0x4E00-9FFF / 0x3400-4DBF / 0xF900-FAFF / 0x3000-303F / 0xFF00-FFEF。
    """
    if text is None:
        return "empty"
    s = str(text).strip()
    if not s:
        return "empty"

    cjk = 0
    latin = 0
    for ch in s:
        o = ord(ch)
        if (
            0x4E00 <= o <= 0x9FFF
            or 0x3400 <= o <= 0x4DBF
            or 0xF900 <= o <= 0xFAFF
            or 0x3000 <= o <= 0x303F
            or 0xFF00 <= o <= 0xFFEF
        ):
            cjk += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1

    if cjk == 0 and latin == 0:
        return "other"
    if cjk > 0 and latin == 0:
        return "zh"
    if latin > 0 and cjk == 0:
        return "en"
    # 混合:谁多跟谁;中英夹杂里中文解说常带少量英文专名
    if cjk >= latin:
        return "zh"
    if latin >= cjk * 2:
        return "en"
    return "mixed"


def speaker_durations(subtitles: list[DubbingSegment], speakers: list) -> dict[str, float]:
    """按行号对齐 zip(subtitles, speakers),累加每条 end_ms-start_ms(毫秒,<=0 跳过)。

    - speakers 可短于 subtitles(zip 天然截断);speakers 长于字幕时同样截断。
    - speaker 无效(normalize 后为 None)的行不计入任何 speaker。
    - 全部时长 <=0 时返回空 dict(有 speaker 但无有效时长)。
    """
    totals: dict[str, float] = {}
    for sub, sp in zip(subtitles, speakers):
        sid = normalize_speaker_id(sp)
        if sid is None:
            continue
        dur = _duration_ms(sub)
        if dur <= 0:
            continue
        totals[sid] = totals.get(sid, 0.0) + dur
    return totals


def pick_narrator(
    durations: dict[str, float],
    min_share: float = DEFAULT_MIN_SHARE,
    preferred_speaker: Optional[str] = None,
) -> dict:
    """按总时长占比选出解说员(主说话人)。

    返回 {
        narrator_speaker_id, narrator_duration_ms, total_speech_ms,
        share, min_share, need_review, reason, metric,
        speaker_durations(按时长降序)
    }

    规则:
    - durations 空或总时长 <=0 → narrator=None, need_review=True, reason='no_labeled_speech'
    - preferred_speaker 有效且在 durations 中 → 强制选它 reason='preferred_speaker';
      指定了但不在 → 回退时长最长者 + need_review=True + reason='preferred_missing_fallback_longest'
    - 常规选时长最长者 reason='longest_speaker'
    - share < min_share → need_review=True
    - 前两名差距 (top1-top2)/total < 0.05 → need_review=True, reason='longest_speaker_close_race'
    - 全部时长 <=0(durations 全 0)也在此处理为 no_labeled_speech(防御)
    """
    total = float(sum(float(v) for v in durations.values()))
    sorted_durations = dict(
        sorted(durations.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    )

    base: dict = {
        "narrator_speaker_id": None,
        "narrator_duration_ms": 0.0,
        "total_speech_ms": total,
        "share": 0.0,
        "min_share": float(min_share),
        "need_review": True,
        "reason": "",
        "metric": "duration",
        "speaker_durations": sorted_durations,
    }

    if not durations or total <= 0:
        base["reason"] = "no_labeled_speech"
        return base

    pref = normalize_speaker_id(preferred_speaker)
    if pref is not None and pref in durations:
        narrator_id = pref
        reason = "preferred_speaker"
    elif pref is not None:
        # 指定了但统计里没有:回退最长并强制复核
        narrator_id = max(durations.items(), key=lambda kv: (float(kv[1]), str(kv[0])))[0]
        reason = "preferred_missing_fallback_longest"
    else:
        narrator_id = max(durations.items(), key=lambda kv: (float(kv[1]), str(kv[0])))[0]
        reason = "longest_speaker"

    narrator_w = float(durations[narrator_id])
    share = narrator_w / total if total > 0 else 0.0
    need_review = share < float(min_share)
    if reason == "preferred_missing_fallback_longest":
        need_review = True

    # 前两名差距过近 → 需人工复核
    ranked = sorted((float(v) for v in durations.values()), reverse=True)
    if len(ranked) >= 2 and total > 0:
        gap_share = (ranked[0] - ranked[1]) / total
        if gap_share < 0.05:
            need_review = True
            if reason == "longest_speaker":
                reason = "longest_speaker_close_race"

    base.update(
        {
            "narrator_speaker_id": narrator_id,
            "narrator_duration_ms": float(durations.get(narrator_id, 0.0)),
            "share": share,
            "need_review": need_review,
            "reason": reason,
        }
    )
    return base


def majority_lang_for_speaker(
    subtitles: list[DubbingSegment], speakers: list, speaker_id: str
) -> str:
    """该 speaker 字幕的按时长加权主导语种;无有效时长时按条数回退;都没有 → 'empty'。"""
    scores: dict[str, float] = {}
    for sub, sp in zip(subtitles, speakers):
        if normalize_speaker_id(sp) != speaker_id:
            continue
        lang = detect_text_lang(sub.text)
        if lang in {"empty", "other"}:
            continue
        w = _duration_ms(sub) or 1.0
        scores[lang] = scores.get(lang, 0.0) + w
    if scores:
        return max(scores.items(), key=lambda kv: (kv[1], kv[0]))[0]

    # 回退:按条数
    counts: dict[str, int] = {}
    for sub, sp in zip(subtitles, speakers):
        if normalize_speaker_id(sp) != speaker_id:
            continue
        lang = detect_text_lang(sub.text)
        if lang in {"empty", "other"}:
            continue
        counts[lang] = counts.get(lang, 0) + 1
    if counts:
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return "empty"


def lang_matches_narrator(seg_lang: str, narrator_lang: str) -> bool:
    """字幕语种是否与解说主导语种一致(可同语保留)。

    - narrator/seg 任一 in {empty, other} → False
    - 相等 → True
    - seg=mixed 且 narrator in {zh, en} → True(宽松匹配)
    """
    if narrator_lang in {"empty", "other"}:
        return False
    if seg_lang in {"empty", "other"}:
        return False
    if seg_lang == narrator_lang:
        return True
    if seg_lang == "mixed" and narrator_lang in {"zh", "en"}:
        return True
    return False


def _dropped_entry(index: int, sub: DubbingSegment, speaker, reason: str) -> dict:
    """构造一条被删明细。text 截 80 字。"""
    return {
        "index": index,
        "start_time": getattr(sub, "start_ms", None),
        "end_time": getattr(sub, "end_ms", None),
        "speaker": speaker,
        "reason": reason,
        "text": str(sub.text or "")[:80],
    }


def filter_narrator_subtitles(
    subtitles: list[DubbingSegment],  # 含 start_ms/end_ms(毫秒)/text
    speakers: list,  # speaker.json 平行数组(长度可与 subtitles 不等)
    min_share: float = DEFAULT_MIN_SHARE,
    keep_same_lang: bool = True,
    keep_unlabeled: bool = False,
    preferred_speaker: Optional[str] = None,
) -> tuple[list[int], dict]:
    """解说字幕过滤:仅保留解说员(主说话人)字幕。

    返回 (kept_indices, report)。kept_indices 为保留行的**原始下标**(升序);
    调用方用它同时切片 subtitles 与 speakers,避免拷贝歧义。

    决策(逐行):
    - speaker 无效 → keep_unlabeled 则留(reason='unlabeled_kept') 否则删('unlabeled_dropped')
    - == narrator → 留('narrator_speaker')
    - keep_same_lang 且 lang_matches_narrator → 留('same_lang_as_narrator')
    - 其余 → 删('other_speaker' 或 'other_speaker_lang_<lang>')

    report 在 pick_narrator 结果上追加:
    kept_count, dropped_count, dropped_unlabeled, kept_by_speaker, kept_by_lang,
    keep_same_lang, keep_unlabeled, narrator_lang, warnings: list[str],
    speakers_len_mismatch: bool,
    dropped: [{index,start_time,end_time,speaker,reason,text(截80字)}](全量被删明细)
    kept_by_lang >= 5 → need_review=True 且 reason 追加 '+lang_rescue'
    speakers 与 subtitles 长度不一致 → warnings 追加说明 + speakers_len_mismatch=True
    """
    warnings: list[str] = []
    speakers_len_mismatch = len(speakers) != len(subtitles)
    if speakers_len_mismatch:
        warnings.append(
            f"speakers 长度 {len(speakers)} 与 subtitles 长度 {len(subtitles)} 不一致,已按 zip 对齐截断"
        )

    durations = speaker_durations(subtitles, speakers)
    pick = pick_narrator(durations, min_share=min_share, preferred_speaker=preferred_speaker)
    narrator_id = pick.get("narrator_speaker_id")

    report: dict = dict(pick)
    report.update(
        {
            "kept_count": 0,
            "dropped_count": 0,
            "dropped_unlabeled": 0,
            "kept_by_speaker": 0,
            "kept_by_lang": 0,
            "keep_same_lang": bool(keep_same_lang),
            "keep_unlabeled": bool(keep_unlabeled),
            "narrator_lang": "empty",
            "warnings": warnings,
            "speakers_len_mismatch": speakers_len_mismatch,
            "dropped": [],
        }
    )

    if narrator_id is None:
        # 选不出解说员(无有效时长/无说话人数据):一条不保留,调用方回退
        dropped = []
        dropped_unlabeled = 0
        for i, sub in enumerate(subtitles):
            sp = speakers[i] if i < len(speakers) else None
            if normalize_speaker_id(sp) is None:
                dropped_unlabeled += 1
            dropped.append(_dropped_entry(i, sub, sp, "no_narrator"))
        report["dropped_count"] = len(subtitles)
        report["dropped_unlabeled"] = dropped_unlabeled
        report["dropped"] = dropped
        return [], report

    narrator_lang = majority_lang_for_speaker(subtitles, speakers, narrator_id)
    report["narrator_lang"] = narrator_lang

    kept: list[int] = []
    kept_by_speaker = 0
    kept_by_lang = 0
    dropped_count = 0
    dropped_unlabeled = 0
    dropped: list[dict] = []

    for i, sub in enumerate(subtitles):
        sp = speakers[i] if i < len(speakers) else None
        sid = normalize_speaker_id(sp)
        seg_lang = detect_text_lang(sub.text)
        reason = ""
        keep = False

        if sid is None:
            if keep_unlabeled:
                keep = True
                reason = "unlabeled_kept"
            else:
                reason = "unlabeled_dropped"
                dropped_count += 1
                dropped_unlabeled += 1
        elif sid == narrator_id:
            keep = True
            reason = "narrator_speaker"
            kept_by_speaker += 1
        elif keep_same_lang and lang_matches_narrator(seg_lang, narrator_lang):
            # 关键:同语种非主 speaker → 多半是 diar 误标的解说
            keep = True
            reason = "same_lang_as_narrator"
            kept_by_lang += 1
        else:
            reason = "other_speaker"
            if keep_same_lang and seg_lang != "empty":
                reason = f"other_speaker_lang_{seg_lang}"
            dropped_count += 1

        if keep:
            kept.append(i)
        else:
            dropped.append(_dropped_entry(i, sub, sp, reason))

    kept_idx = sorted(kept)
    report.update(
        {
            "kept_count": len(kept_idx),
            "dropped_count": dropped_count,
            "dropped_unlabeled": dropped_unlabeled,
            "kept_by_speaker": kept_by_speaker,
            "kept_by_lang": kept_by_lang,
            "dropped": dropped,
        }
    )

    # 同语救回条目较多时提醒人工复核(通常是预期行为,但值得看一眼)
    if kept_by_lang >= 5:
        report["need_review"] = True
        report["reason"] = str(report.get("reason") or "") + "+lang_rescue"

    return kept_idx, report
