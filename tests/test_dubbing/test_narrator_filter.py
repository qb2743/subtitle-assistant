"""Tests for narrator filtering (``core/dubbing/narrator_filter.py``).

Ports pyVideoTrans's ``narrator_filter.py`` algorithm, adapted to
``DubbingSegment`` + parallel ``speakers`` array.
"""

from videocaptioner.core.dubbing.models import DubbingSegment
from videocaptioner.core.dubbing.narrator_filter import (
    detect_text_lang,
    filter_narrator_subtitles,
    lang_matches_narrator,
    normalize_speaker_id,
    pick_narrator,
)


def seg(index, start_ms, end_ms, text):
    return DubbingSegment(index=index, start_ms=start_ms, end_ms=end_ms, text=text)


def _zh_segs(*ranges):
    return [seg(i + 1, s, e, "这是解说内容示例文本") for i, (s, e) in enumerate(ranges)]


# ------------------------------------------------------------ languages


def test_detect_text_lang():
    assert detect_text_lang("这是中文解说") == "zh"
    assert detect_text_lang("hello world") == "en"
    # 拉丁字符占比 >= 2x 中文 → 判 en(与移植算法一致)。
    assert detect_text_lang("中文 with English") == "en"
    assert detect_text_lang("这是中文一些内容English中文") == "zh"
    assert detect_text_lang("") == "empty"
    assert detect_text_lang(None) == "empty"
    assert detect_text_lang("12345") == "other"


def test_normalize_speaker_id():
    assert normalize_speaker_id("spk0") == "spk0"
    assert normalize_speaker_id("") is None
    assert normalize_speaker_id(None) is None
    assert normalize_speaker_id("  ") is None
    assert normalize_speaker_id("unknown") is None


def test_lang_matches_narrator():
    assert lang_matches_narrator("zh", "zh") is True
    assert lang_matches_narrator("mixed", "zh") is True
    assert lang_matches_narrator("en", "zh") is False
    assert lang_matches_narrator("other", "zh") is False


# ------------------------------------------------------------ single speaker


def test_single_speaker_all_kept():
    subs = _zh_segs((0, 1000), (1000, 2000), (2000, 3000))
    speakers = ["spk0", "spk0", "spk0"]
    kept, report = filter_narrator_subtitles(subs, speakers)
    assert kept == [0, 1, 2]
    assert report["dropped_count"] == 0
    assert report["narrator_speaker_id"] == "spk0"
    assert report["need_review"] is False


# ------------------------------------------------------------ majority speaker


def test_majority_speaker_kept_other_dropped():
    # spk0 占 3000ms,spk1 占 1000ms → 主说话人 spk0,spk1 被删。
    subs = _zh_segs((0, 1000), (1000, 2000), (2000, 3000)) + [seg(4, 4000, 5000, "spk1 line")]
    speakers = ["spk0", "spk0", "spk0", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers)
    assert kept == [0, 1, 2]
    assert report["dropped_count"] == 1
    assert report["dropped"][0]["reason"] == "other_speaker"
    assert report["narrator_speaker_id"] == "spk0"


# ------------------------------------------------------------ min_share boundary


def test_min_share_boundary_triggers_review():
    # spk0 300ms,spk1 240ms,spk2 180ms → share=300/720=0.417 < 0.45 → need_review。
    subs = [
        seg(1, 0, 300, "一"),
        seg(2, 500, 740, "二"),
        seg(3, 1000, 1180, "三"),
    ]
    speakers = ["spk0", "spk1", "spk2"]
    kept, report = filter_narrator_subtitles(subs, speakers, min_share=0.45)
    assert report["narrator_speaker_id"] == "spk0"
    assert report["need_review"] is True
    assert report["share"] < 0.45


# ------------------------------------------------------------ close race


def test_close_race_between_top_two_triggers_review():
    # spk0 1000ms,spk1 980ms → 差距 (20/1980)=1% < 5% → need_review。
    subs = [seg(1, 0, 1000, "甲"), seg(2, 2000, 2980, "乙")]
    speakers = ["spk0", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers)
    assert report["narrator_speaker_id"] == "spk0"
    assert report["need_review"] is True
    assert report["reason"] == "longest_speaker_close_race"


# ------------------------------------------------------------ same-lang rescue


def test_default_strict_filter_drops_same_language_dialogue():
    # 文本语种不能覆盖说话人结果：同为中文的 spk1 原片对白仍应进入严格删除集。
    subs = [
        seg(1, 0, 2000, "眼前这位男子正准备离开房间"),
        seg(2, 2000, 3000, "你到底要去哪里"),
    ]
    speakers = ["spk0", "spk1"]

    kept, report = filter_narrator_subtitles(subs, speakers)

    assert kept == [0]
    assert report["keep_same_lang"] is False
    assert report["kept_by_lang"] == 0
    assert report["dropped"] == [
        {
            "index": 1,
            "start_time": 2000,
            "end_time": 3000,
            "speaker": "spk1",
            "reason": "other_speaker",
            "text": "你到底要去哪里",
        }
    ]


def test_keep_same_lang_rescues_mislabeled_narrator():
    # 主说话人 spk0(2000ms, 中文);spk1 也是中文(500ms)→ 同语救回,保留。
    subs = [
        seg(1, 0, 2000, "这是解说的开场白内容"),
        seg(2, 2000, 2500, "眼前这位男子看起来很紧张"),
    ]
    speakers = ["spk0", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers, keep_same_lang=True)
    assert kept == [0, 1]
    assert report["narrator_speaker_id"] == "spk0"
    assert report["narrator_lang"] == "zh"
    assert report["kept_by_lang"] == 1


def test_keep_same_lang_does_not_rescue_different_language():
    # spk0 时长更长(2000ms)为主说话人;spk1 是英文,与中文解说不同语 → 删除。
    subs = [
        seg(1, 0, 2000, "这是解说的开场白内容"),
        seg(2, 0, 1000, "Hello, how are you."),
    ]
    speakers = ["spk0", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers, keep_same_lang=True)
    assert kept == [0]
    assert report["dropped_count"] == 1


# ------------------------------------------------------------ keep_unlabeled


def test_keep_unlabeled_keeps_empty_label():
    # spk1 用英文,避免同语救回;仅验证空标签行为。
    subs = [
        seg(1, 0, 2000, "这是解说的开场白内容"),
        seg(2, 0, 1000, "这是未标注的一句话"),
        seg(3, 0, 1000, "Hello there."),
    ]
    speakers = ["spk0", "", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers, keep_unlabeled=True)
    assert kept == [0, 1]  # 空标签被保留
    assert report["kept_by_speaker"] == 1


def test_keep_unlabeled_false_drops_empty_label():
    subs = [
        seg(1, 0, 2000, "这是解说的开场白内容"),
        seg(2, 0, 1000, "这是未标注的一句话"),
        seg(3, 0, 1000, "Hello there."),
    ]
    speakers = ["spk0", "", "spk1"]
    kept, report = filter_narrator_subtitles(subs, speakers, keep_unlabeled=False)
    assert kept == [0]
    assert report["dropped_unlabeled"] == 1


# ------------------------------------------------------------ no narrator


def test_no_labeled_speech_returns_empty_and_review():
    subs = _zh_segs((0, 1000), (2000, 3000))
    speakers = ["", ""]
    kept, report = filter_narrator_subtitles(subs, speakers)
    assert kept == []
    assert report["narrator_speaker_id"] is None
    assert report["need_review"] is True
    assert report["reason"] == "no_labeled_speech"


# ------------------------------------------------------------ length mismatch


def test_speakers_len_mismatch_warns_and_truncates():
    subs = _zh_segs((0, 1000), (2000, 3000), (4000, 5000))
    speakers = ["spk0", "spk0"]  # 短于字幕
    kept, report = filter_narrator_subtitles(subs, speakers)
    assert report["speakers_len_mismatch"] is True
    assert report["warnings"]
    # 第三行无 speaker → 默认删除(keep_unlabeled=False)。
    assert kept == [0, 1]


# ------------------------------------------------------------ pick_narrator


def test_pick_narrator_preferred_speaker():
    pick = pick_narrator({"spk0": 100.0, "spk1": 900.0}, preferred_speaker="spk0")
    assert pick["narrator_speaker_id"] == "spk0"
    assert pick["reason"] == "preferred_speaker"
