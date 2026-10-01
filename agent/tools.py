"""Tool definitions the LLM can call, in Anthropic tool-use format."""

from datetime import date

SYSTEM_PROMPT = """You are a careful web-browsing agent. You complete the user's task by \
controlling a real Chromium browser, one action at a time.

After every action you receive an observation: the current URL, a numbered list of \
interactive elements, and the visible page text. Refer to elements by their number.

How to work:
- Before each action, write one short sentence on what you are doing and why.
- Pick a sensible starting site yourself (for trains in Great Britain, nationalrail.co.uk \
or thetrainline.com; for general questions, a search engine such as duckduckgo.com).
- Dismiss cookie banners and pop-ups when they block the page.
- If a page does not show what you need, scroll or use read_text before giving up.
- If you are stuck after a few attempts, try a different site or approach.
- Today's date is {today}. Resolve words like "tomorrow" into real dates.

Safety rules (never break these):
- Never buy anything, enter payment details, log in, or create accounts.
- Never type personal information. If a task needs it, use ask_human.
- Stop before any checkout or booking confirmation and report what you found.

When you have the answer, call finish with a clear, specific answer including the \
key facts (prices, times, names) and the URL where you found them. If the task is \
impossible, call finish with success=false and explain why."""


def system_prompt() -> str:
    return SYSTEM_PROMPT.format(today=date.today().strftime("%A %d %B %Y"))


TOOLS = [
    {
        "name": "navigate",
        "description": "Open a URL in the current tab.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL or domain"}},
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an interactive element by its number from the latest observation.",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "type_text",
        "description": "Replace the contents of an input field with text. "
        "Set submit=true to press Enter afterwards (e.g. for search boxes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "text": {"type": "string"},
                "submit": {"type": "boolean", "default": False},
            },
            "required": ["element_id", "text"],
        },
    },
    {
        "name": "select_option",
        "description": "Choose an option in a <select> dropdown by its visible label.",
        "input_schema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}, "option": {"type": "string"}},
            "required": ["element_id", "option"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key, e.g. Enter, Escape, Tab, ArrowDown.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the page to reveal more elements.",
        "input_schema": {
            "type": "object",
            "properties": {"direction": {"type": "string", "enum": ["up", "down"]}},
            "required": ["direction"],
        },
    },
    {
        "name": "go_back",
        "description": "Go back to the previous page.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_text",
        "description": "Read a later part of the current page's visible text "
        "(the observation only shows the first part).",
        "input_schema": {
            "type": "object",
            "properties": {"page": {"type": "integer", "minimum": 0}},
            "required": ["page"],
        },
    },
    {
        "name": "ask_human",
        "description": "Ask the user a question when you need information or a decision "
        "you cannot make yourself.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "finish",
        "description": "End the task and give the final answer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "success": {"type": "boolean"},
            },
            "required": ["answer", "success"],
        },
    },
]
