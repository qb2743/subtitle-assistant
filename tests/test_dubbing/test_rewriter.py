from types import SimpleNamespace

from videocaptioner.core.dubbing.models import DubbingConfig, DubbingSegment
from videocaptioner.core.dubbing.rewriter import rewrite_segments_if_needed


def test_rewriter_switches_to_backup_model(monkeypatch):
    import videocaptioner.core.dubbing.rewriter as rewriter_mod
    import videocaptioner.core.llm.client as client_mod

    monkeypatch.setattr(client_mod, "_preferred_models", {})
    attempts = []

    class FailoverCompletions:
        def create(self, **kwargs):
            attempts.append(kwargs["model"])
            if kwargs["model"] == "primary":
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="not json")
                        )
                    ]
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"items":[{"index":1,"text":"精简文案"}]}'
                        )
                    )
                ]
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailoverCompletions())
    )
    openai_kwargs = {}

    def fake_openai(**kwargs):
        openai_kwargs.update(kwargs)
        return client

    monkeypatch.setattr(rewriter_mod, "OpenAI", fake_openai)

    segment = DubbingSegment(
        index=1,
        start_ms=0,
        end_ms=1000,
        text="这是一条明显超过目标时长的测试字幕",
    )
    config = DubbingConfig(
        provider="edge",
        api_key="",
        base_url="",
        model="edge-tts",
        rewrite_too_long=True,
        llm_api_key="sk-fake",
        llm_api_base="http://fake",
        llm_model="primary, backup",
    )

    rewrite_segments_if_needed([segment], config)

    assert attempts == ["primary", "backup"]
    assert segment.rewritten_text == "精简文案"
    assert openai_kwargs["base_url"] == "http://fake/v1"
