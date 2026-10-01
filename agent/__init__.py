"""mini-browser-agent: an LLM that browses the web with Playwright."""

from .browser import BrowserSession
from .core import Agent, Result

__all__ = ["Agent", "BrowserSession", "Result"]
