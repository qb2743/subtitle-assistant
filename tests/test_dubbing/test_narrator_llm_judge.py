"""Tests for LLM narrator review (``core/dubbing/narrator_llm_judge.py``).

Mocks ``call_llm`` so no network call happens; verifies the restore logic,
bad-JSON retry, out-of-range index filtering, and missing-LLM-fields path.
"""

import json
import os

import videocaptioner.core.dubbing.narrator_llm_judge as nj
from videocaptioner.core.dubbing.models import DubbingSegment


def seg(index, start_ms, end_ms, text):
    return DubbingSegment(index=index, start_ms=start_ms, end_ms=end_ms, text=text)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


def _llm_fields():
    return ("test-key", "https://api.test.example/v1", "test-model")


# ------------------------------------------------------------ prompt builder


def test_build_judge_user_prompt_includes_items_and_samples():
    prompt = nj.build_judge_user_prompt(
        [
            {"i": 0, "start": 83450, "end": 90000, "speaker_id": "spk1", "text": "我们走吧"},
        ],
        narrator_hint="眼前这位男子",
        style_samples=["已经判定为解说的样例"],
    )
    assert "主说话人(时长最长,仅供参考): 眼前这位男子" in prompt
    assert "已判定为解说的样例" in prompt
    assert "[0] t=01:23.45-01:30.00 speaker=spk1 | 我们走吧" in prompt
    assert "请输出 JSON 数组。" in prompt


def test_fmt_ms_invalid_returns_question():
    assert nj._fmt_ms(None) == "?"
    assert nj._fmt_ms(-5) == "?"


# ------------------------------------------------------------ parse / pick


def test_parse_judge_response_handles_thinking_blocks_and_fences():
    raw = (
        "<thinking>我会仔细判断</thinking>\n"
        "```json\n"
        '[{"i":0,"label":"narrator","reason":"解说口吻"}]'
        "\n```"
    )
    parsed = nj.parse_judge_response(raw, expected_ids=[0, 1])
    assert parsed[0]["label"] == "narrator"
    assert 1 not in parsed


def test_parse_judge_response_filters_out_of_range():
    raw = json.dumps(
        [{"i": 0, "label": "narrator", "reason": "r"},
         {"i": 99, "label": "narrator", "reason": "r"}]
    )
    parsed = nj.parse_judge_response(raw, expected_ids=[0, 1])
    assert list(parsed.keys()) == [0]


def test_parse_judge_response_bad_json_returns_empty():
    assert nj.parse_judge_response("not json", expected_ids=[0]) == {}
    assert nj.parse_judge_response("", expected_ids=[0]) == {}
    assert nj.parse_judge_response(None, expected_ids=[0]) == {}


def test_pick_restore_indices():
    judged = {
        0: {"label": "narrator"},
        1: {"label": "dialogue"},
        2: {"label": "unsure"},
    }
    assert nj.pick_restore_indices(judged) == [0]
    assert nj.pick_restore_indices(judged, restore_unsure=True) == [0, 2]


# ------------------------------------------------------------ judge_dropped


def test_judge_dropped_normal_json_restores_narrator(monkeypatch):
    kept = [seg(1, 0, 1000, "这是解说的开头")]
    dropped = [
        seg(2, 1000, 2000, "角色说:我们走吧"),
        seg(3, 2000, 3000, "解说:这时他回来了"),
    ]
    content = json.dumps([{"i": 1, "label": "narrator", "reason": "解说口吻"}])

    calls = []

    def fake_call_llm(**kw):
        calls.append(kw)
        return FakeResponse(content)

    monkeypatch.setattr(nj, "call_llm", fake_call_llm)

    result = nj.judge_dropped(kept, dropped, _llm_fields())
    assert result == [1]  # dropped 下标 1(id 3 的那条)。


def test_judge_dropped_exposes_details_for_manual_review(monkeypatch):
    content = json.dumps(
        [{"i": 0, "label": "dialogue", "reason": "角色对白"}]
    )
    monkeypatch.setattr(nj, "call_llm", lambda **kw: FakeResponse(content))
    details = {}

    result = nj.judge_dropped(
        [],
        [seg(1, 0, 1000, "我们走吧")],
        _llm_fields(),
        details_callback=details.update,
    )

    assert result == []
    assert details == {0: {"label": "dialogue", "reason": "角色对白"}}


def test_judge_dropped_retries_once_on_bad_json(monkeypatch):
    kept = [seg(1, 0, 1000, "开头")]
    dropped = [seg(2, 0, 1000, "甲"), seg(3, 1000, 2000, "乙")]
    calls = []

    def fake_call_llm(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return FakeResponse("this is not json [")
        return FakeResponse(json.dumps([{"i": 0, "label": "narrator", "reason": "x"}]))

    monkeypatch.setattr(nj, "call_llm", fake_call_llm)

    result = nj.judge_dropped(kept, dropped, _llm_fields())
    assert len(calls) == 2  # 坏 JSON → 重试 1 次。
    assert result == [0]


def test_judge_dropped_returns_empty_after_repeated_failure(monkeypatch):
    kept = [seg(1, 0, 1000, "开头")]
    dropped = [seg(2, 0, 1000, "甲")]
    calls = []

    def fake_call_llm(**kw):
        calls.append(kw)
        return FakeResponse("still not json")

    monkeypatch.setattr(nj, "call_llm", fake_call_llm)

    result = nj.judge_dropped(kept, dropped, _llm_fields())
    assert len(calls) == 2
    assert result == []


def test_judge_dropped_filters_out_of_range_restore(monkeypatch):
    dropped = [seg(1, 0, 1000, "甲"), seg(2, 1000, 2000, "乙")]
    # 模型输出的 i=5 不在 dropped 范围内 → 过滤,不恢复。
    content = json.dumps([{"i": 5, "label": "narrator", "reason": "x"}])

    monkeypatch.setattr(nj, "call_llm", lambda **kw: FakeResponse(content))

    result = nj.judge_dropped([], dropped, _llm_fields())
    assert result == []


def test_judge_dropped_missing_llm_fields_skips_call(monkeypatch):
    called = []
    monkeypatch.setattr(
        nj, "call_llm", lambda **kw: called.append(1) or FakeResponse("[]")
    )
    result = nj.judge_dropped([], [seg(1, 0, 1000, "x")], ("", "", ""))
    assert result == []
    assert called == []



def test_judge_dropped_restores_env_vars(monkeypatch):
    os.environ["OPENAI_API_KEY"] = "original-key"
    os.environ["OPENAI_BASE_URL"] = "https://original.example/v1"
    kept = [seg(1, 0, 1000, "开头")]
    dropped = [seg(2, 0, 1000, "甲")]
    monkeypatch.setattr(
        nj,
        "call_llm",
        lambda **kw: FakeResponse(json.dumps([{"i": 0, "label": "narrator", "reason": "r"}])),
    )
    nj.judge_dropped(kept, dropped, _llm_fields())
    assert os.environ["OPENAI_API_KEY"] == "original-key"
    assert os.environ["OPENAI_BASE_URL"] == "https://original.example/v1"


def test_judge_dropped_empty_dropped_returns_empty(monkeypatch):
    called = []
    monkeypatch.setattr(
        nj, "call_llm", lambda **kw: called.append(1) or FakeResponse("[]")
    )
    assert nj.judge_dropped([], [], _llm_fields()) == []
    assert called == []
