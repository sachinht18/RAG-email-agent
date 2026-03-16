from __future__ import annotations

from dataclasses import dataclass

import pytest

from email_sdr_flow.runtime import invoke_structured_stage, invoke_text_stage
from email_sdr_flow.schemas import RetrievalPlan
from email_sdr_flow.errors import StageExecutionError


@dataclass
class FakeResponse:
    content: object


class FakeStructuredModel:
    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        return self._responses.pop(0)


class FakeTextModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return FakeResponse(content=self.content)


def test_invoke_structured_stage_retries_after_invalid_output(monkeypatch):
    monkeypatch.setenv("EMAIL_SDR_STAGE_RETRIES", "1")
    model = FakeStructuredModel(
        [
            {"query": "", "intent": ""},
            {"query": "product docs", "intent": "find safe proof"},
        ]
    )

    result = invoke_structured_stage(
        stage_name="query_planning",
        model=model,
        schema=RetrievalPlan,
        messages=[("human", "test")],
    )

    assert result.query == "product docs"


def test_invoke_structured_stage_raises_when_output_never_valid(monkeypatch):
    monkeypatch.setenv("EMAIL_SDR_STAGE_RETRIES", "0")
    model = FakeStructuredModel([{"query": "", "intent": ""}])

    with pytest.raises(StageExecutionError) as exc_info:
        invoke_structured_stage(
            stage_name="query_planning",
            model=model,
            schema=RetrievalPlan,
            messages=[("human", "test")],
        )

    assert exc_info.value.code == "invalid_structured_output"


def test_invoke_text_stage_rejects_empty_text():
    model = FakeTextModel("")

    with pytest.raises(StageExecutionError) as exc_info:
        invoke_text_stage(
            stage_name="final_reasoning",
            model=model,
            messages=[("human", "test")],
        )

    assert exc_info.value.code == "empty_text_output"
