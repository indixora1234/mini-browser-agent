# 🧭 mini-browser-agent

![tests](https://github.com/indixora1234/mini-browser-agent/actions/workflows/tests.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

An LLM that uses a real web browser to complete tasks you describe in plain English.

```bash
python -m agent "Find the cheapest train from London to Bristol tomorrow"
```

The agent opens Chromium, decides where to go, clicks, types and scrolls its way through real websites, and reports back with an answer and the page it came from.

<!-- Add a demo GIF here: record a run with the browser visible, then drop the GIF in docs/demo.gif -->
<!-- ![demo](docs/demo.gif) -->

## How it works

The agent runs a simple **observe → think → act** loop:

```
┌────────────┐   page snapshot    ┌─────────┐   tool call    ┌────────────┐
│ Playwright │ ─────────────────▶ │   LLM   │ ─────────────▶ │  Execute   │
│  browser   │ ◀───────────────── │ (Claude)│                │  action    │
└────────────┘     next action    └─────────┘                └────────────┘
```

1. **Observe.** JavaScript injected into the page finds every visible interactive element (links, buttons, inputs, dropdowns), gives each a number, and collects the visible text. The model sees something like:
   ```
   URL: https://www.nationalrail.co.uk/
   Interactive elements:
     [0] <input> From station
     [1] <input> To station
     [4] <button> Get times and prices
   Visible text (part 1 of 3): ...
   ```
2. **Think.** The model explains its next move in one sentence, then calls a tool such as `click(4)` or `type_text(0, "London")`.
3. **Act.** Playwright performs the action and the loop repeats until the model calls `finish`.

### Design decisions

- **Numbered elements instead of CSS selectors.** Models are unreliable at writing selectors for unfamiliar pages, but very good at picking "element 4". The ids are written into the DOM as `data-agent-id`, so each action maps back to exactly one element.
- **Text first, screenshots optional.** A text snapshot is much cheaper than an image and works for most sites. `--vision` adds screenshots for visually complex pages.
- **Only the newest observation stays in context.** Old page snapshots are stale and expensive, so they are trimmed after each step while the action history is kept. This keeps long tasks within the context window and cuts costs.
- **Errors go back to the model.** If a click fails or an element has gone, the error is returned as the action result so the model can recover, instead of the whole run crashing.
- **Safety rails in code, not just in the prompt.** Typing into password fields is blocked in the browser layer, and the system prompt forbids purchases, logins and personal data. An `ask_human` tool lets the agent ask you when it is unsure.

## Quick start

```bash
git clone https://github.com/indixora1234/mini-browser-agent.git
cd mini-browser-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then add your Anthropic API key
```

Run a task:

```bash
python -m agent "What is the top story on Hacker News right now?"
python -m agent "Find the cheapest train from London to Bristol tomorrow morning"
python -m agent "What's the weather forecast for Edinburgh this weekend?" --headless
```

| Flag | What it does |
|---|---|
| `--headless` | Hide the browser window |
| `--max-steps N` | Stop after N actions (default 25) |
| `--vision` | Also send screenshots to the model |
| `--model NAME` | Use a different Claude model |
| `--no-trace` | Don't save screenshots and `trace.json` |

Each run saves a screenshot per step and a full `trace.json` in `runs/<timestamp>/`, which is useful for debugging and for making demo GIFs.

## Tools the agent can use

`navigate` · `click` · `type_text` · `select_option` · `press_key` · `scroll` · `go_back` · `read_text` · `ask_human` · `finish`

## Tests

The tests run a real headless browser against a local test page with a scripted fake LLM, so they need no API key and run in CI on every push.

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Limitations

- Sites with strong bot protection or CAPTCHAs may block the agent.
- Complex custom widgets (date pickers, canvas maps) sometimes need `--vision`.
- It will not log in, buy anything or enter personal data, by design.

## Project structure

```
agent/
  browser.py   Playwright wrapper and page snapshot logic
  core.py      The agent loop, context trimming and run traces
  tools.py     Tool schemas and system prompt
  __main__.py  Command-line interface
tests/         Offline tests with a fake LLM
```

## Background

I built a similar internal AI browser agent during my internship at Elitery. This is an independent, open-source reimplementation of the core idea, written from scratch to show the approach publicly.

## License

MIT
