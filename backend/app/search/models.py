from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    text: str = ""
