"""Offline tests: a real browser on a local page, with a scripted fake LLM."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import Agent, BrowserSession
from agent.core import OBS_MARKER

PAGE = (Path(__file__).parent / "fixtures" / "trains.html").resolve().as_uri()


def tool_call(name, **args):
    return SimpleNamespace(type="tool_use", id=f"call_{name}", name=name, input=args)


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    """Mimics client.messages.create, returning a fixed script of responses."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.script.pop(0))


async def test_snapshot_lists_elements():
    async with BrowserSession(headless=True) as browser:
        await browser.navigate(PAGE)
        snap = await browser.snapshot()
        labels = [e["label"] for e in snap.elements]
        assert labels == ["From station", "To station", "Password", "Search"]
        assert "Test Trains" in snap.render()


async def test_password_fields_are_blocked():
    async with BrowserSession(headless=True) as browser:
        await browser.navigate(PAGE)
        await browser.snapshot()
        with pytest.raises(PermissionError):
            await browser.type_text(2, "hunter2")


async def test_agent_completes_task_with_fake_llm():
    client = FakeClient([
        [text("Opening the test site."), tool_call("navigate", url=PAGE)],
        [tool_call("type_text", element_id=0, text="London")],
        [tool_call("type_text", element_id=1, text="Bristol")],
        [tool_call("click", element_id=3)],
        [text("The cheapest is 10:30."), tool_call("finish", answer="10:30 for £23.50", success=True)],
    ])
    agent = Agent(client=client, runs_dir=None)
    async with BrowserSession(headless=True) as browser:
        result = await agent.run("Find the cheapest train", browser)

    assert result.success
    assert result.answer == "10:30 for £23.50"
    assert [s.action for s in result.steps] == ["navigate", "type_text", "type_text", "click", "finish"]

    # The model saw the search results after clicking.
    user_turns = [m for m in client.calls[-1]["messages"] if m["role"] == "user"]
    last_prompt = user_turns[-1]["content"][-1]["content"]
    assert "£23.50" in last_prompt

    # Only the newest observation is kept in the conversation.
    all_user_text = str([m["content"] for m in user_turns])
    assert all_user_text.count(OBS_MARKER) == 1


async def test_errors_are_returned_to_the_model():
    client = FakeClient([
        [tool_call("click", element_id=99)],
        [tool_call("finish", answer="gave up", success=False)],
    ])
    agent = Agent(client=client, runs_dir=None)
    async with BrowserSession(headless=True) as browser:
        await browser.navigate(PAGE)
        result = await agent.run("Click something missing", browser)

    assert "No element with id 99" in result.steps[0].outcome
    assert not result.success
