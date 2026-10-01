"""Command-line entry point: python -m agent "your task" """

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .browser import BrowserSession
from .core import DEFAULT_MODEL, Agent


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Give an LLM a browser and a task.")
    parser.add_argument("task", help='e.g. "Find the cheapest train from London to Bristol tomorrow"')
    parser.add_argument("--headless", action="store_true", help="hide the browser window")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--vision", action="store_true", help="also send screenshots to the model")
    parser.add_argument("--no-trace", action="store_true", help="don't save screenshots and trace.json")
    args = parser.parse_args()

    console = Console()
    console.print(Panel(args.task, title="Task", border_style="cyan"))

    async def go():
        agent = Agent(
            model=args.model,
            max_steps=args.max_steps,
            vision=args.vision,
            runs_dir=None if args.no_trace else Path("runs"),
            console=console,
        )
        async with BrowserSession(headless=args.headless) as browser:
            return await agent.run(args.task, browser)

    result = asyncio.run(go())
    style = "green" if result.success else "red"
    console.print(Panel(result.answer, title=f"Result ({len(result.steps)} steps)", border_style=style))
    if result.run_dir:
        console.print(f"[dim]Trace and screenshots saved to {result.run_dir}/[/]")


if __name__ == "__main__":
    main()
