"""The agent loop: observe the page, ask the LLM for an action, execute it, repeat."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from .browser import BrowserSession
from .tools import TOOLS, system_prompt

DEFAULT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
OBS_MARKER = "--- OBSERVATION ---"


@dataclass
class Step:
    number: int
    thought: str
    action: str
    args: dict
    outcome: str
    url: str


@dataclass
class Result:
    task: str
    success: bool
    answer: str
    steps: list[Step] = field(default_factory=list)
    run_dir: str | None = None


class Agent:
    def __init__(
        self,
        client: Any = None,
        model: str = DEFAULT_MODEL,
        max_steps: int = 25,
        vision: bool = False,
        runs_dir: Path | None = Path("runs"),
        ask_human: Callable[[str], str] = input,
        console: Console | None = None,
    ):
        if client is None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY
        self.client = client
        self.model = model
        self.max_steps = max_steps
        self.vision = vision
        self.runs_dir = runs_dir
        self.ask_human = ask_human
        self.console = console or Console()

    async def run(self, task: str, browser: BrowserSession) -> Result:
        run_dir = self._make_run_dir()
        result = Result(task=task, success=False, answer="", run_dir=str(run_dir) if run_dir else None)
        text_page = 0

        snap = await browser.snapshot()
        messages: list[dict] = [
            {
                "role": "user",
                "content": f"Task: {task}\n\n{OBS_MARKER}\n{snap.render()}",
            }
        ]

        for step_no in range(1, self.max_steps + 1):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt(),
                tools=TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            thought = " ".join(b.text for b in response.content if b.type == "text").strip()
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if thought:
                self.console.print(f"[bold cyan]Step {step_no}[/] [dim]{thought}[/]")

            if not tool_calls:
                messages.append({"role": "user", "content": "Please continue by calling a tool. Use finish when done."})
                continue

            tool_results = []
            for call in tool_calls:
                name, args = call.name, dict(call.input)
                self.console.print(f"  [yellow]→ {name}[/] {json.dumps(args, ensure_ascii=False)}")

                if name == "finish":
                    result.success = bool(args.get("success"))
                    result.answer = args.get("answer", "")
                    result.steps.append(Step(step_no, thought, name, args, "finished", browser.page.url))
                    self._save(run_dir, result)
                    return result

                outcome, text_page = await self._execute(browser, name, args, text_page)
                self.console.print(f"  [green]✓[/] {outcome}")
                result.steps.append(Step(step_no, thought, name, args, outcome, browser.page.url))
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": outcome})

            # Attach a fresh observation to the last result only.
            snap = await browser.snapshot()
            observation = f"{tool_results[-1]['content']}\n\n{OBS_MARKER}\n{snap.render(text_page)}"
            if self.vision:
                shot = await browser.screenshot()
                tool_results[-1]["content"] = [
                    {"type": "text", "text": observation},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(shot).decode()},
                    },
                ]
            else:
                tool_results[-1]["content"] = observation

            if run_dir:
                await browser.screenshot(run_dir / f"step_{step_no:02d}.jpg")

            self._trim_old_observations(messages)
            messages.append({"role": "user", "content": tool_results})

        result.answer = f"Stopped after reaching the limit of {self.max_steps} steps."
        self._save(run_dir, result)
        return result

    async def _execute(self, browser: BrowserSession, name: str, args: dict, text_page: int) -> tuple[str, int]:
        """Run one action. Errors go back to the model as text so it can recover."""
        try:
            if name == "read_text":
                return f"Showing text part {args['page'] + 1}", args["page"]
            if name == "ask_human":
                answer = self.ask_human(f"\n🤖 Agent asks: {args['question']}\n> ")
                return f"Human answered: {answer}", text_page
            if name == "navigate":
                return await browser.navigate(args["url"]), 0
            if name == "click":
                return await browser.click(int(args["element_id"])), 0
            if name == "type_text":
                return await browser.type_text(int(args["element_id"]), args["text"], bool(args.get("submit"))), 0
            if name == "select_option":
                return await browser.select_option(int(args["element_id"]), args["option"]), text_page
            if name == "press_key":
                return await browser.press_key(args["key"]), 0
            if name == "scroll":
                return await browser.scroll(args.get("direction", "down")), text_page
            if name == "go_back":
                return await browser.go_back(), 0
            return f"Error: unknown tool {name}", text_page
        except Exception as exc:  # noqa: BLE001 - surface any browser error to the model
            message = str(exc).splitlines()[0][:300]
            return f"Error running {name}: {message}", text_page

    @staticmethod
    def _trim_old_observations(messages: list[dict]) -> None:
        """Old page snapshots are stale and expensive, so keep only the newest one.

        The action outcome lines stay, so the model still remembers what it did.
        """
        for msg in messages:
            if msg["role"] != "user":
                continue
            content = msg["content"]
            if isinstance(content, str) and OBS_MARKER in content:
                msg["content"] = content.split(OBS_MARKER)[0] + "(old observation removed)"
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    inner = block["content"]
                    if isinstance(inner, list):  # vision mode: drop the old image
                        inner = next((b["text"] for b in inner if b["type"] == "text"), "")
                    if OBS_MARKER in inner:
                        inner = inner.split(OBS_MARKER)[0].strip() + "\n(old observation removed)"
                    block["content"] = inner

    def _make_run_dir(self) -> Path | None:
        if self.runs_dir is None:
            return None
        run_dir = self.runs_dir / time.strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def _save(run_dir: Path | None, result: Result) -> None:
        if run_dir:
            (run_dir / "trace.json").write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
