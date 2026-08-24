"""text_matches_target_language 的文字体系判定测试。"""

from videocaptioner.core.translate.types import (
    TargetLanguage,
    text_matches_target_language,
)


def test_chinese_text_matches_chinese_target():
    assert text_matches_target_language("这是一段中文解说", TargetLanguage.SIMPLIFIED_CHINESE)


def test_english_text_matches_english_target():
    assert text_matches_target_language("This is a line.", TargetLanguage.ENGLISH)
    # 判定按文字体系而非具体语种：法语等拉丁字母文本对英语目标同样视为"已是目标语言"
    assert text_matches_target_language("C'est une phrase française.", TargetLanguage.ENGLISH_US)


def test_mixed_chinese_with_english_words_is_chinese():
    """中文里夹少量英文单词，主体仍是中文。"""
    assert not text_matches_target_language("我觉得这个 OK 的啊", TargetLanguage.ENGLISH)


def test_russian_text_matches_russian_only():
    assert text_matches_target_language("Привет мир", TargetLanguage.RUSSIAN)
    assert not text_matches_target_language("Привет мир", TargetLanguage.ENGLISH)
    assert not text_matches_target_language("Привет мир", TargetLanguage.SIMPLIFIED_CHINESE)


def test_japanese_kana_and_kanji():
    assert text_matches_target_language("これはペンです", TargetLanguage.JAPANESE)
    # 纯汉字文本无法与中文区分，日语目标一并接受
    assert text_matches_target_language("東京タワー", TargetLanguage.JAPANESE)


def test_text_without_letters_does_not_match():
    assert not text_matches_target_language("123...", TargetLanguage.ENGLISH)
    assert not text_matches_target_language("", TargetLanguage.ENGLISH)
