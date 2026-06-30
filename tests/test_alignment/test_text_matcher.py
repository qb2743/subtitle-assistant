"""Tests for the align_text_to_asr adapter (ASRData <-> DTW dict format)."""

from videocaptioner.core.alignment import align_text_to_asr
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg


def test_align_text_to_asr_round_trip():
    asr = ASRData(
        [
            ASRDataSeg(text="你好世界", start_time=0, end_time=2000),
            ASRDataSeg(text="今天天气真好", start_time=2000, end_time=4000),
        ]
    )
    aligned = align_text_to_asr(asr, "你好世界\n今天天气真好", max_chars=30)
    assert isinstance(aligned, ASRData)
    assert len(aligned.segments) == 2
    assert aligned.segments[0].text == "你好世界"
    assert aligned.segments[1].text == "今天天气真好"
    # Timings are ms, first starts near 0, second after the first, no overlap.
    assert 0 <= aligned.segments[0].start_time < 500
    assert aligned.segments[1].start_time > aligned.segments[0].start_time
    assert aligned.segments[0].end_time <= aligned.segments[1].start_time
    assert aligned.segments[-1].end_time <= 4500


def test_align_text_to_asr_corrects_text():
    # ASR misheard; the user's correct text wins, timing comes from ASR.
    asr = ASRData([ASRDataSeg(text="你好师姐", start_time=0, end_time=2000)])
    aligned = align_text_to_asr(asr, "你好世界", max_chars=30)
    assert aligned.segments[0].text == "你好世界"
    assert 0 <= aligned.segments[0].start_time <= 2000


def test_align_text_to_asr_produces_srt():
    asr = ASRData([ASRDataSeg(text="你好世界", start_time=0, end_time=2000)])
    aligned = align_text_to_asr(asr, "你好世界", max_chars=30)
    srt = aligned.to_srt()
    assert "你好世界" in srt
    assert "-->" in srt


def test_align_text_to_asr_preserves_punctuation():
    # Punctuation guides DTW splitting but is stripped from the final subtitle
    # text (only ASCII apostrophe ' survives).
    asr = ASRData([ASRDataSeg(text="你好世界", start_time=0, end_time=2000)])
    aligned = align_text_to_asr(asr, "你好，世界！", max_chars=30)
    assert aligned.segments[0].text == "你好世界"


def test_align_text_to_asr_default_uses_txt2srt_length_split():
    asr = ASRData(
        [
            ASRDataSeg(
                text="一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十",
                start_time=0,
                end_time=8000,
            ),
        ]
    )
    aligned = align_text_to_asr(
        asr,
        "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十",
    )
    assert len(aligned.segments) == 2


def test_align_text_to_asr_auto_language_keeps_english_words_intact():
    text = "entered from the dry cave on the left to provide support and brought Juhos body out"
    asr = ASRData([ASRDataSeg(text=text, start_time=0, end_time=8000)])

    aligned = align_text_to_asr(asr, text, max_chars=30, language="auto")

    joined = "|".join(seg.text for seg in aligned.segments)
    assert "supp|ort" not in joined
    assert "support" in joined
    assert all(len(word) > 1 for seg in aligned.segments for word in seg.text.split())



    # max_chars=0 means no length cap, but paragraphs still split by sentence.
    asr = ASRData(
        [
            ASRDataSeg(text="你好世界今天天气真好我们去公园", start_time=0, end_time=6000),
        ]
    )
    aligned = align_text_to_asr(asr, "你好世界。今天天气真好！我们去公园！", max_chars=0)
    assert len(aligned.segments) == 3
    # Punctuation used for splitting is stripped from the displayed text.
    assert aligned.segments[0].text == "你好世界"
    assert aligned.segments[1].text == "今天天气真好"
    assert aligned.segments[2].text == "我们去公园"
