"""Unit tests for the ElevenLabs API key parser."""

from videocaptioner.core.speech import parse_api_keys


def test_empty_returns_empty_list():
    assert parse_api_keys("") == []
    assert parse_api_keys(None) == []


def test_single_key():
    assert parse_api_keys("key1") == ["key1"]


def test_comma_separated():
    assert parse_api_keys("key1, key2, key3") == ["key1", "key2", "key3"]


def test_semicolon_separated():
    assert parse_api_keys("key1;key2;key3") == ["key1", "key2", "key3"]


def test_mixed_separators_and_fullwidth():
    # ASCII comma/semicolon, whitespace, and full-width ，；
    assert parse_api_keys("key1, key2；key3，key4 key5") == [
        "key1",
        "key2",
        "key3",
        "key4",
        "key5",
    ]


def test_strips_whitespace_and_empties():
    assert parse_api_keys("  key1  ,  , key2  ") == ["key1", "key2"]
