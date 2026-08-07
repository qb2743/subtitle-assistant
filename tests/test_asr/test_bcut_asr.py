"""BcutASR integration tests."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import videocaptioner.core.asr.bcut as bcut_module
from tests.test_asr.conftest import assert_asr_result_valid
from videocaptioner.core.asr import BcutASR
from videocaptioner.core.asr.asr_data import ASRData


def test_result_retries_transient_ssl_error(monkeypatch):
    asr = BcutASR.__new__(BcutASR)
    asr.task_id = "task-id"
    response = Mock()
    response.json.return_value = {"data": {"state": 4}}
    get = Mock(
        side_effect=[requests.exceptions.SSLError("unexpected eof"), response]
    )
    sleeps = []
    monkeypatch.setattr(bcut_module.requests, "get", get)
    monkeypatch.setattr(bcut_module.time, "sleep", sleeps.append)

    assert asr.result() == {"state": 4}
    assert get.call_count == 2
    assert get.call_args.kwargs["timeout"] == bcut_module.RESULT_REQUEST_TIMEOUT
    assert get.call_args.kwargs["params"]["task_id"] == "task-id"
    assert sleeps == [1]


def test_result_stops_after_bounded_network_retries(monkeypatch):
    asr = BcutASR.__new__(BcutASR)
    asr.task_id = "task-id"
    error = requests.exceptions.Timeout("timed out")
    get = Mock(side_effect=error)
    sleeps = []
    monkeypatch.setattr(bcut_module.requests, "get", get)
    monkeypatch.setattr(bcut_module.time, "sleep", sleeps.append)

    with pytest.raises(requests.exceptions.Timeout, match="timed out"):
        asr.result()

    assert get.call_count == bcut_module.RESULT_REQUEST_ATTEMPTS
    assert sleeps == [1, 2]


def test_result_does_not_retry_http_errors(monkeypatch):
    asr = BcutASR.__new__(BcutASR)
    asr.task_id = "task-id"
    response = Mock()
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("403")
    get = Mock(return_value=response)
    sleep = Mock()
    monkeypatch.setattr(bcut_module.requests, "get", get)
    monkeypatch.setattr(bcut_module.time, "sleep", sleep)

    with pytest.raises(requests.exceptions.HTTPError, match="403"):
        asr.result()

    get.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.integration
@pytest.mark.slow
class TestBcutASR:
    """Test suite for BcutASR using public Bilibili API.

    Note: This service has rate limits and should be used sparingly.
    Tests are marked as 'slow' to avoid running in normal CI.
    """

    @pytest.fixture
    def bcut_asr_sentence(self, test_audio_path: Path) -> BcutASR:
        """Create BcutASR instance with sentence-level timestamps.

        Args:
            test_audio_path: Path to test audio file

        Returns:
            BcutASR instance configured for sentence-level timestamps
        """
        return BcutASR(
            audio_input=str(test_audio_path),
            need_word_time_stamp=False,
        )

    @pytest.fixture
    def bcut_asr_word(self, test_audio_path: Path) -> BcutASR:
        """Create BcutASR instance with word-level timestamps.

        Args:
            test_audio_path: Path to test audio file

        Returns:
            BcutASR instance configured for word-level timestamps
        """
        return BcutASR(
            audio_input=str(test_audio_path),
            need_word_time_stamp=True,
        )

    # def test_transcribe_sentence_level(self, bcut_asr_sentence: BcutASR) -> None:
    #     """Test sentence-level transcription (need_word_time_stamp=False).

    #     Args:
    #         bcut_asr_sentence: BcutASR instance with sentence-level timestamps
    #     """
    #     result: ASRData = bcut_asr_sentence.run()

    #     print("\n" + "=" * 60)
    #     print("BcutASR Sentence-Level Transcription Results:")
    #     print(f"  Total segments: {len(result.segments)}")
    #     print(f"  Is word timestamp: {result.is_word_timestamp()}")
    #     for i, seg in enumerate(result.segments[:3], 1):
    #         print(f"  [{i}] {seg.text} ({seg.start_time}-{seg.end_time}ms)")
    #     print("=" * 60)

    #     assert_asr_result_valid(result, min_segments=0)
    #     assert (
    #         not result.is_word_timestamp()
    #     ), "Result should be sentence-level, not word-level"

    # def test_transcribe_word_level(self, bcut_asr_word: BcutASR) -> None:
    #     """Test word-level transcription (need_word_time_stamp=True).

    #     Args:
    #         bcut_asr_word: BcutASR instance with word-level timestamps
    #     """
    #     result: ASRData = bcut_asr_word.run()

    #     print("\n" + "=" * 60)
    #     print("BcutASR Word-Level Transcription Results:")
    #     print(f"  Total segments: {len(result.segments)}")
    #     print(f"  Is word timestamp: {result.is_word_timestamp()}")
    #     for i, seg in enumerate(result.segments[:5], 1):
    #         print(f"  [{i}] {seg.text} ({seg.start_time}-{seg.end_time}ms)")
    #     print("=" * 60)

    #     assert_asr_result_valid(result, min_segments=0)

    #     if len(result.segments) > 0:
    #         assert (
    #             result.is_word_timestamp()
    #         ), "Result should be word-level when need_word_time_stamp=True"

    @pytest.mark.parametrize(
        "need_word_ts,audio_fixture",
        [
            (False, "test_audio_path_zh"),
            (True, "test_audio_path_zh"),
            (False, "test_audio_path_en"),
            (True, "test_audio_path_en"),
        ],
    )
    def test_transcribe_parametrized(
        self, need_word_ts: bool, audio_fixture: str, request
    ) -> None:
        """Test transcription with different configurations and languages.

        Args:
            need_word_ts: Whether to use word-level timestamps
            audio_fixture: Name of the audio fixture to use
            request: Pytest request object for fixture access
        """
        audio_path: Path = request.getfixturevalue(audio_fixture)
        lang = "Chinese" if "zh" in audio_fixture else "English"
        level = "word" if need_word_ts else "sentence"

        asr = BcutASR(
            audio_input=str(audio_path),
            need_word_time_stamp=need_word_ts,
        )

        result: ASRData = asr.run()

        print("\n" + "=" * 60)
        print(f"BcutASR - {lang.upper()} - {level.title()}-Level Results:")
        print(f"  Total Segments: {len(result.segments)}")
        print(f"  Is Word Timestamp: {result.is_word_timestamp()}")
        for i, seg in enumerate(result.segments[:50], 1):
            print(
                f"    [{i:2d}] {seg.text:<30} ({seg.start_time:6d} - {seg.end_time:6d} ms)"
            )
        print("=" * 60)

        assert_asr_result_valid(result, min_segments=0)

        if not need_word_ts and len(result.segments) > 0:
            assert not result.is_word_timestamp()
