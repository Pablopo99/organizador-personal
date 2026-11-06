from unittest.mock import patch

import pytest
import requests

import llm_client


class _Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def _ok(message):
    return _Resp(200, {"choices": [{"message": message}]})


ANTHROPIC_TOOL = {
    "name": "add_task",
    "description": "Añade una tarea",
    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
}


def test_to_openai_tools_converts_anthropic_format():
    out = llm_client.to_openai_tools([ANTHROPIC_TOOL])
    assert out == [{
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Añade una tarea",
            "parameters": ANTHROPIC_TOOL["input_schema"],
        },
    }]


def test_chat_sends_system_first_model_and_tools(monkeypatch):
    monkeypatch.setattr(llm_client, "AIKIT_MODEL", "fast")
    monkeypatch.setattr(llm_client, "AIKIT_API_KEY", "aik_test")
    msg = {"role": "assistant", "content": "hola"}
    with patch("llm_client.requests.post", return_value=_ok(msg)) as post:
        result = llm_client.chat(
            system="SYS",
            messages=[{"role": "user", "content": "hi"}],
            tools=[ANTHROPIC_TOOL],
        )
    assert result == msg
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer aik_test"
    body = kwargs["json"]
    assert body["model"] == "fast"
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}
    assert body["tools"][0]["function"]["name"] == "add_task"


def test_chat_does_not_mutate_caller_messages():
    messages = [{"role": "user", "content": "hi"}]
    with patch("llm_client.requests.post", return_value=_ok({"role": "assistant", "content": "x"})):
        llm_client.chat(system="SYS", messages=messages, tools=[])
    assert messages == [{"role": "user", "content": "hi"}]


def test_chat_429_raises_rate_limit_error():
    resp = _Resp(429, {"error": {"code": "ORG_BUDGET_EXCEEDED"}})
    with patch("llm_client.requests.post", return_value=resp):
        with pytest.raises(llm_client.RateLimitError):
            llm_client.chat(system="S", messages=[], tools=[])


def test_chat_retries_once_on_5xx_then_succeeds():
    msg = {"role": "assistant", "content": "ok"}
    with patch("llm_client.requests.post", side_effect=[_Resp(502), _ok(msg)]) as post, \
         patch("llm_client.time.sleep"):
        assert llm_client.chat(system="S", messages=[], tools=[]) == msg
    assert post.call_count == 2


def test_chat_retries_on_timeout_then_raises_llm_error():
    with patch("llm_client.requests.post", side_effect=requests.Timeout("lento")), \
         patch("llm_client.time.sleep"):
        with pytest.raises(llm_client.LLMError):
            llm_client.chat(system="S", messages=[], tools=[])


def test_chat_4xx_raises_llm_error_without_retry():
    with patch("llm_client.requests.post", return_value=_Resp(401)) as post:
        with pytest.raises(llm_client.LLMError):
            llm_client.chat(system="S", messages=[], tools=[])
    assert post.call_count == 1


def test_chat_malformed_body_raises_llm_error():
    with patch("llm_client.requests.post", return_value=_Resp(200, {"nope": 1})):
        with pytest.raises(llm_client.LLMError):
            llm_client.chat(system="S", messages=[], tools=[])
