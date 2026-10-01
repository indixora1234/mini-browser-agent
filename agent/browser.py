"""Playwright wrapper that turns a live web page into text an LLM can act on.

Every visible interactive element (links, buttons, inputs...) gets a numeric
id written into the DOM as ``data-agent-id``. The LLM sees a numbered list and
answers with actions like ``click(7)``, which we resolve back to the element.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# Runs inside the page. Tags interactive elements and returns a compact snapshot.
SNAPSHOT_JS = r"""
(maxElements) => {
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = window.getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') return false;
    // Only things on screen or just below it, to keep the list short.
    return r.bottom > 0 && r.top < window.innerHeight * 2;
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim().slice(0, 80);

  document.querySelectorAll('[data-agent-id]').forEach((e) => e.removeAttribute('data-agent-id'));

  const selector = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=tab]', '[role=option]', '[role=menuitem]',
    '[role=checkbox]', '[role=radio]', '[role=combobox]', '[role=searchbox]',
    '[contenteditable=true]', '[onclick]',
  ].join(',');

  const elements = [];
  for (const el of document.querySelectorAll(selector)) {
    if (elements.length >= maxElements) break;
    if (!isVisible(el)) continue;
    const id = elements.length;
    el.setAttribute('data-agent-id', String(id));
    const tag = el.tagName.toLowerCase();
    const isField = ['input', 'textarea', 'select'].includes(tag);
    const label = clean(
      el.getAttribute('aria-label') ||
      (isField ? (el.getAttribute('placeholder') || el.getAttribute('name')) : el.innerText) ||
      el.getAttribute('title') || el.getAttribute('alt') || el.value || ''
    );
    elements.push({
      id,
      tag,
      type: el.getAttribute('type') || el.getAttribute('role') || '',
      label,
      value: isField && el.type !== 'password' ? clean(el.value) : '',
      href: tag === 'a' ? (el.getAttribute('href') || '').slice(0, 100) : '',
    });
  }

  const text = document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n') : '';
  return { elements, text };
}
"""

TEXT_CHUNK = 4000  # characters of visible page text shown per observation


@dataclass
class Snapshot:
    url: str
    title: str
    elements: list[dict]
    text: str

    def render(self, text_page: int = 0) -> str:
        """Format the snapshot as plain text for the LLM."""
        lines = [f"URL: {self.url}", f"Title: {self.title}", "", "Interactive elements:"]
        if not self.elements:
            lines.append("  (none visible)")
        for el in self.elements:
            desc = f"[{el['id']}] <{el['tag']}"
            if el["type"]:
                desc += f" {el['type']}"
            desc += f"> {el['label'] or '(no label)'}"
            if el["value"]:
                desc += f"  (current value: {el['value']})"
            if el["href"] and not el["href"].startswith("javascript"):
                desc += f"  -> {el['href']}"
            lines.append("  " + desc)

        start = text_page * TEXT_CHUNK
        chunk = self.text[start : start + TEXT_CHUNK]
        total_pages = max(1, -(-len(self.text) // TEXT_CHUNK))
        lines += ["", f"Visible text (part {text_page + 1} of {total_pages}):", chunk or "(empty)"]
        if text_page + 1 < total_pages:
            lines.append(f"... more text available, use read_text(page={text_page + 1})")
        return "\n".join(lines)


class BrowserSession:
    """A single browser tab the agent drives, plus helpers for each action."""

    def __init__(self, headless: bool = False, max_elements: int = 80):
        self.headless = headless
        self.max_elements = max_elements
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._last: Snapshot | None = None

    async def __aenter__(self) -> "BrowserSession":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="en-GB"
        )
        self.page = await self._context.new_page()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ----- observation -----------------------------------------------------

    async def snapshot(self) -> Snapshot:
        await self._settle()
        data = await self.page.evaluate(SNAPSHOT_JS, self.max_elements)
        self._last = Snapshot(
            url=self.page.url,
            title=await self.page.title(),
            elements=data["elements"],
            text=data["text"],
        )
        return self._last

    async def screenshot(self, path: Path | None = None) -> bytes:
        return await self.page.screenshot(path=path, type="jpeg", quality=60)

    # ----- actions ---------------------------------------------------------

    async def navigate(self, url: str) -> str:
        if not re.match(r"^[a-z]+://", url) and not url.startswith("about:"):
            url = "https://" + url
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return f"Navigated to {self.page.url}"

    async def click(self, element_id: int) -> str:
        el = self._element(element_id)
        pages_before = len(self._context.pages)
        await self._locator(element_id).click(timeout=8_000)
        await self.page.wait_for_timeout(500)
        # Follow links that open in a new tab.
        if len(self._context.pages) > pages_before:
            self.page = self._context.pages[-1]
            await self.page.bring_to_front()
            return f"Clicked [{element_id}] {el['label']!r}; it opened a new tab, now on {self.page.url}"
        return f"Clicked [{element_id}] {el['label']!r}"

    async def type_text(self, element_id: int, text: str, submit: bool = False) -> str:
        el = self._element(element_id)
        if el["type"] == "password":
            raise PermissionError("Typing into password fields is blocked for safety.")
        loc = self._locator(element_id)
        try:
            await loc.fill(text, timeout=8_000)
        except Exception:
            # Some custom widgets reject fill(); fall back to real keystrokes.
            await loc.click(timeout=8_000)
            await self.page.keyboard.type(text, delay=30)
        if submit:
            await self.page.keyboard.press("Enter")
        return f"Typed {text!r} into [{element_id}]" + (" and pressed Enter" if submit else "")

    async def select_option(self, element_id: int, option: str) -> str:
        await self._locator(element_id).select_option(label=option, timeout=8_000)
        return f"Selected {option!r} in [{element_id}]"

    async def press_key(self, key: str) -> str:
        await self.page.keyboard.press(key)
        return f"Pressed {key}"

    async def scroll(self, direction: str = "down") -> str:
        delta = 700 if direction == "down" else -700
        await self.page.mouse.wheel(0, delta)
        await self.page.wait_for_timeout(400)
        return f"Scrolled {direction}"

    async def go_back(self) -> str:
        await self.page.go_back(wait_until="domcontentloaded", timeout=15_000)
        return f"Went back to {self.page.url}"

    # ----- internals -------------------------------------------------------

    def _element(self, element_id: int) -> dict:
        if self._last is None:
            raise ValueError("No snapshot yet; look at the page first.")
        for el in self._last.elements:
            if el["id"] == element_id:
                return el
        raise ValueError(f"No element with id {element_id} on the current page.")

    def _locator(self, element_id: int):
        return self.page.locator(f'[data-agent-id="{element_id}"]').first

    async def _settle(self) -> None:
        """Give the page a moment to finish loading before we read it."""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=3_000)
        except Exception:
            pass  # Busy sites never go fully idle; carry on with what's there.
