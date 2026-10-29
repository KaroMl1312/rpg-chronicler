import json
import subprocess

import pytest

from rpg_chronicler.llm import LLMError, get_client, with_retry
from rpg_chronicler.llm import claude_code
from rpg_chronicler.llm.claude_code import ClaudeCodeClient


def test_with_retry_retries_retryable_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = iter([LLMError("przeciążony"), LLMError("przeciążony"), "OK"])

    def flaky():
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    assert with_retry(flaky, "test", attempts=3, delay=0) == "OK"


def test_with_retry_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def always_fails():
        calls.append(1)
        raise LLMError("limit")

    with pytest.raises(LLMError):
        with_retry(always_fails, "test", attempts=3, delay=0)
    assert len(calls) == 3


def test_with_retry_does_not_retry_permanent_errors():
    calls = []

    def bad_request():
        calls.append(1)
        raise LLMError("zły klucz", retryable=False)

    with pytest.raises(LLMError):
        with_retry(bad_request, "test", attempts=3, delay=0)
    assert len(calls) == 1


def test_get_client_rejects_unknown_provider():
    with pytest.raises(LLMError) as e:
        get_client("chatgpt")
    assert not e.value.retryable


def fake_run(stdout, returncode=0, stderr=""):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run, calls


def test_claude_code_sends_prompt_on_stdin_without_tools(monkeypatch):
    run, calls = fake_run(json.dumps({"is_error": False, "result": "Kronika"}))
    monkeypatch.setattr(claude_code.subprocess, "run", run)

    assert ClaudeCodeClient(model="sonnet").generate("PROMPT") == "Kronika"
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert kwargs["input"] == "PROMPT"


def test_claude_code_reports_errors(monkeypatch):
    run, _ = fake_run(json.dumps({"is_error": True, "result": "Usage limit reached"}), returncode=1)
    monkeypatch.setattr(claude_code.subprocess, "run", run)
    with pytest.raises(LLMError, match="Usage limit"):
        ClaudeCodeClient().generate("x")


def test_claude_code_handles_non_json_output(monkeypatch):
    run, _ = fake_run("coś poszło nie tak", returncode=1)
    monkeypatch.setattr(claude_code.subprocess, "run", run)
    with pytest.raises(LLMError, match="Nieoczekiwana odpowiedź"):
        ClaudeCodeClient().generate("x")


def test_claude_code_missing_binary_is_permanent(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr(claude_code.subprocess, "run", run)
    with pytest.raises(LLMError) as e:
        ClaudeCodeClient().generate("x")
    assert not e.value.retryable
