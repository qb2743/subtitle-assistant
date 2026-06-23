"""Tests for the ElevenLabs SDK voice listing helper.

The elevenlabs SDK client is replaced with a fake so no network access is
needed.
"""

from types import SimpleNamespace

import pytest

import videocaptioner.core.speech.providers as providers_module
from videocaptioner.core.speech import list_elevenlabs_voices


class _FakeVoice:
    def __init__(self, voice_id, name, category, labels, preview_url):
        self.voice_id = voice_id
        self.name = name
        self.category = category
        self.labels = labels
        self.preview_url = preview_url


class _FakeVoicesClient:
    def __init__(self):
        self.get_all_calls: list = []

    def get_all(self, *, show_legacy=None, request_options=None):
        self.get_all_calls.append(show_legacy)
        return SimpleNamespace(
            voices=[
                _FakeVoice(
                    "21m00Tcm4TlvDq8ikWAM",
                    "Rachel",
                    "premade",
                    {"gender": "female"},
                    "https://example.com/rachel.mp3",
                ),
                _FakeVoice("cloned123", "My Clone", "cloned", None, ""),
            ]
        )


class _FakeClient:
    instances: list = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.voices = _FakeVoicesClient()
        _FakeClient.instances.append(self)


@pytest.fixture(autouse=True)
def _install_fake(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(providers_module, "ElevenLabs", _FakeClient)
    yield


def test_list_voices_normalizes_fields():
    voices = list_elevenlabs_voices("el-key", base_url="https://api.example.com", timeout=30)
    assert voices == [
        {
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "name": "Rachel",
            "category": "premade",
            "labels": {"gender": "female"},
            "preview_url": "https://example.com/rachel.mp3",
        },
        {
            "voice_id": "cloned123",
            "name": "My Clone",
            "category": "cloned",
            "labels": {},
            "preview_url": "",
        },
    ]
    # Client built with the supplied credentials.
    assert _FakeClient.instances[-1].init_kwargs["api_key"] == "el-key"
    assert _FakeClient.instances[-1].init_kwargs["timeout"] == 30


def test_list_voices_default_includes_legacy():
    list_elevenlabs_voices("el-key")
    voices_client = _FakeClient.instances[-1].voices
    assert voices_client.get_all_calls == [True]


def test_list_voices_can_exclude_legacy():
    list_elevenlabs_voices("el-key", include_legacy=False)
    voices_client = _FakeClient.instances[-1].voices
    assert voices_client.get_all_calls == [False]


def test_list_voices_requires_api_key():
    with pytest.raises(ValueError):
        list_elevenlabs_voices("")
