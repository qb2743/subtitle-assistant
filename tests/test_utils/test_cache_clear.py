"""Tests for cache clearing functionality."""

import pytest
from diskcache import Cache

import videocaptioner.core.utils.cache as cache_module


ALL_CACHE_NAMES = [
    "llm_translation",
    "asr_results",
    "tts_audio",
    "translate_results",
    "version_state",
]


@pytest.fixture
def tmp_all_caches(tmp_path, monkeypatch):
    """Point ALL_CACHES at temporary cache instances for isolated testing."""
    mapping = {
        name: Cache(str(tmp_path / name)) for name in ALL_CACHE_NAMES
    }
    monkeypatch.setattr(cache_module, "ALL_CACHES", mapping)
    yield mapping
    for cache in mapping.values():
        cache.close()


class TestClearCaches:
    """Test suite for the clear_caches function."""

    def test_clear_all_caches(self, tmp_all_caches) -> None:
        """Test that calling clear_caches() empties every cache."""
        for cache in tmp_all_caches.values():
            cache.set("key", "value")
            assert len(cache) == 1

        result = cache_module.clear_caches()

        assert set(result) == set(ALL_CACHE_NAMES)
        for name, cache in tmp_all_caches.items():
            assert result[name] == 1
            assert len(cache) == 0

    def test_clear_selected_caches(self, tmp_all_caches) -> None:
        """Test that only the specified caches are cleared."""
        for cache in tmp_all_caches.values():
            cache.set("key", "value")

        result = cache_module.clear_caches(names=["llm_translation", "translate_results"])

        assert set(result) == {"llm_translation", "translate_results"}
        # Selected caches are emptied
        assert len(tmp_all_caches["llm_translation"]) == 0
        assert len(tmp_all_caches["translate_results"]) == 0
        # Unselected caches are preserved
        assert len(tmp_all_caches["asr_results"]) == 1
        assert len(tmp_all_caches["tts_audio"]) == 1
        assert len(tmp_all_caches["version_state"]) == 1

    def test_clear_empty_cache(self, tmp_all_caches) -> None:
        """Test that clearing already-empty caches is a no-op without error."""
        result = cache_module.clear_caches()

        assert set(result) == set(ALL_CACHE_NAMES)
        assert all(count == 0 for count in result.values())
