from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from backend.config import WEB_SEARCH_ENABLED

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_CACHE_TTL = timedelta(minutes=30)
_cache: dict[str, tuple[datetime, list[dict]]] = {}
_cache_lock = Lock()


class _ResultsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._active: str | None = None
        self._active_tag = ""
        self._depth = 0
        self._text: list[str] = []
        self._href = ""
        self._titles: list[tuple[str, str]] = []
        self._snippets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._active is None:
            if tag == "a" and "result__a" in classes:
                self._begin("title", tag, attributes.get("href") or "")
            elif "result__snippet" in classes:
                self._begin("snippet", tag, "")
            return
        if tag == self._active_tag:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._active is None or tag != self._active_tag:
            return
        self._depth -= 1
        if self._depth:
            return
        text = " ".join("".join(self._text).replace("\ufffd", " ").split())
        if self._active == "title" and text and self._href:
            self._titles.append((text[:200], self._href))
        elif self._active == "snippet" and text:
            self._snippets.append(text[:600])
        self._active = None
        self._active_tag = ""
        self._text = []
        self._href = ""

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            self._text.append(data)

    def _begin(self, kind: str, tag: str, href: str) -> None:
        self._active = kind
        self._active_tag = tag
        self._depth = 1
        self._text = []
        self._href = href

    def sources(self, limit: int) -> list[dict]:
        for index, (title, href) in enumerate(self._titles):
            url = _result_url(href)
            if not url:
                continue
            self.results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": self._snippets[index] if index < len(self._snippets) else "",
                    "source_type": "Live web result (review before use)",
                    "level": "Suggested",
                }
            )
            if len(self.results) >= limit:
                break
        return self.results


def _result_url(href: str) -> str | None:
    absolute = urljoin(_SEARCH_URL, href)
    parsed = urlsplit(absolute)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path == "/l/":
        absolute = parse_qs(parsed.query).get("uddg", [""])[0]
        parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return absolute


def search_web(query: str, limit: int = 3) -> tuple[list[dict], str | None]:
    if not WEB_SEARCH_ENABLED:
        return [], "External web search is disabled."
    normalized = " ".join(query.split())[:300]
    if not normalized:
        return [], "External web search needs a non-empty query."
    limit = min(max(limit, 1), 5)
    cache_key = f"{normalized.casefold()}|{limit}"
    now = datetime.now(timezone.utc)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1], None if cached[1] else "External web search returned no usable results."

    try:
        response = httpx.get(
            _SEARCH_URL,
            params={"q": normalized},
            headers={"User-Agent": "NorthStar career learning advisor"},
            timeout=8,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        message = (
            f"External web search returned HTTP {status}."
            if status is not None
            else "External web search could not be reached."
        )
        return [], message

    parser = _ResultsParser()
    parser.feed(response.text)
    results = parser.sources(limit)
    with _cache_lock:
        _cache[cache_key] = (now, results)
    error = None if results else "External web search returned no usable results."
    return results, error


def learning_resources_for_skills(skills: list[str]) -> tuple[dict[str, list[dict]], bool]:
    selected = list(dict.fromkeys(skills))[:3]
    if not selected:
        return {}, False
    results: dict[str, list[dict]] = {}
    failures = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=min(3, len(selected))) as executor:
        futures = {
            executor.submit(
                search_web,
                f"official learning resources tutorial for {skill}",
                1,
            ): skill
            for skill in selected
        }
        for future in as_completed(futures):
            skill = futures[future]
            sources, error = future.result()
            if error:
                failures += 1
            elif sources:
                results[skill] = sources
    return results, failures > 0
