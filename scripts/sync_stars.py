#!/usr/bin/env python3
"""Synchronize the authenticated user's GitHub stars into this repository."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.github.com/user/starred?per_page=100"
ACCEPT = "application/vnd.github.star+json"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "starred.json"
README_PATH = ROOT / "README.md"
START_MARKER = "<!-- STAR-COLLECTOR:START -->"
END_MARKER = "<!-- STAR-COLLECTOR:END -->"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_dataset() -> dict[str, Any]:
    return {"schema_version": 1, "last_sync": None, "repositories": []}


def load_dataset(path: Path = DATA_PATH) -> dict[str, Any]:
    if not path.exists():
        return empty_dataset()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read existing dataset {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("repositories"), list):
        raise RuntimeError(f"Existing dataset {path} has an invalid structure")
    return value


def parse_next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def retry_delay(error: HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), 60.0)
    reset = error.headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        return min(max(float(reset) - time.time(), 1.0), 60.0)
    return min(2 ** (attempt - 1), 8)


def fetch_page(url: str, token: str) -> tuple[list[Any], str | None]:
    headers = {
        "Accept": ACCEPT,
        "Authorization": f"Bearer {token}",
        "User-Agent": "star-collector",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as response:
                body = json.load(response)
                if not isinstance(body, list):
                    raise RuntimeError(f"GitHub returned a non-list response for {url}")
                return body, parse_next_link(response.headers.get("Link"))
        except HTTPError as exc:
            temporary = exc.code in {403, 408, 429} or 500 <= exc.code < 600
            remaining = exc.headers.get("X-RateLimit-Remaining")
            if not temporary or attempt == MAX_ATTEMPTS:
                detail = f"HTTP {exc.code}"
                if remaining == "0":
                    detail += "; API rate limit exhausted"
                raise RuntimeError(f"GitHub stars request failed after {attempt} attempt(s): {detail}") from exc
            delay = retry_delay(exc, attempt)
            print(f"Temporary GitHub HTTP {exc.code}; retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"GitHub stars request failed after {attempt} attempts: {exc}") from exc
            delay = min(2 ** (attempt - 1), 8)
            print(f"Temporary network error; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
    raise AssertionError("retry loop exited unexpectedly")


def fetch_all_starred(token: str) -> list[dict[str, Any]]:
    url: str | None = API_URL
    results: list[dict[str, Any]] = []
    visited: set[str] = set()
    while url:
        if url in visited:
            raise RuntimeError("GitHub pagination returned a repeated next-page URL")
        visited.add(url)
        page, url = fetch_page(url, token)
        for position, item in enumerate(page, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("repo"), dict):
                raise RuntimeError(f"Incomplete GitHub response: invalid item {position} on page {len(visited)}")
            if item["repo"].get("id") is None:
                raise RuntimeError(f"Incomplete GitHub response: repository ID missing on page {len(visited)}")
            results.append(item)
    return results


def normalize_record(item: dict[str, Any], existing: dict[str, Any] | None, sync_time: str) -> dict[str, Any]:
    repo = item["repo"]
    owner = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
    repo_id = int(repo["id"])
    starred_at = item.get("starred_at") or (existing or {}).get("starred_at") or sync_time

    def field(name: str, default: Any = None) -> Any:
        if name in repo:
            return repo[name]
        return (existing or {}).get(name, default)

    return {
        "id": repo_id,
        "name": field("name", "") or "",
        "owner": owner.get("login") or (existing or {}).get("owner") or "",
        "full_name": field("full_name", "") or "",
        "html_url": field("html_url", "") or "",
        "description": field("description"),
        "language": field("language"),
        "stargazers_count": field("stargazers_count", 0),
        "topics": sorted(field("topics", []) or []),
        "updated_at": field("updated_at"),
        "starred_at": starred_at,
        "homepage": field("homepage"),
        "starred": True,
        "unstarred_at": None,
    }


def merge_dataset(existing_data: dict[str, Any], starred_items: list[dict[str, Any]], sync_time: str) -> dict[str, Any]:
    existing_by_id: dict[int, dict[str, Any]] = {}
    for record in existing_data.get("repositories", []):
        if isinstance(record, dict) and record.get("id") is not None:
            existing_by_id[int(record["id"])] = record

    current_by_id: dict[int, dict[str, Any]] = {}
    for item in starred_items:
        repo_id = int(item["repo"]["id"])
        current_by_id[repo_id] = normalize_record(item, existing_by_id.get(repo_id), sync_time)

    merged: list[dict[str, Any]] = []
    for repo_id, record in existing_by_id.items():
        if repo_id in current_by_id:
            merged.append(current_by_id.pop(repo_id))
            continue
        historical = dict(record)
        if historical.get("starred", True):
            historical["starred"] = False
            historical["unstarred_at"] = historical.get("unstarred_at") or sync_time
        merged.append(historical)
    merged.extend(current_by_id.values())
    merged.sort(key=lambda record: int(record["id"]))

    old_repositories = existing_data.get("repositories", [])
    changed = merged != old_repositories or existing_data.get("last_sync") is None
    return {
        "schema_version": 1,
        "last_sync": sync_time if changed else existing_data.get("last_sync"),
        "repositories": merged,
    }


def markdown_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def short_stars(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "0"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m".replace(".0m", "m")
    if number >= 1_000:
        return f"{number / 1_000:.1f}k".replace(".0k", "k")
    return str(number)


def render_managed_block(dataset: dict[str, Any], static_content: str = "") -> str:
    active = [record for record in dataset["repositories"] if record.get("starred")]
    active.sort(key=lambda record: (record.get("starred_at") or "", record.get("full_name") or ""), reverse=True)
    visible = [record for record in active if not record.get("html_url") or record["html_url"] not in static_content]
    lines = [START_MARKER]
    for record in visible:
        name = markdown_cell(record.get("full_name"))
        url = record.get("html_url") or "#"
        description = markdown_cell(record.get("description")) or "No description available."
        lines.append(f"- [{name}]({url}) - {description}")
    if visible:
        lines[-1] += f" {END_MARKER}"
    else:
        lines[0] += END_MARKER
    return "\n".join(lines)


def render_readme(dataset: dict[str, Any], existing_readme: str = "") -> str:
    static_content = existing_readme
    if START_MARKER in existing_readme and END_MARKER in existing_readme:
        before, remainder = existing_readme.split(START_MARKER, 1)
        _, after = remainder.split(END_MARKER, 1)
        static_content = before + after
        return before + render_managed_block(dataset, static_content) + after

    block = render_managed_block(dataset, static_content)
    repositories_header = re.search(r"(?m)^## Repositories[^\n]*\n", existing_readme)
    if repositories_header:
        next_header = re.search(r"(?m)^## ", existing_readme[repositories_header.end():])
        section_end = repositories_header.end() + next_header.start() if next_header else len(existing_readme)
        before = existing_readme[:section_end].rstrip()
        after = existing_readme[section_end:].lstrip("\n")
        return before + "\n\n" + block + "\n\n" + after

    fallback = "# ⭐ My Starred Repositories\n\nAutomatically synchronized from my GitHub stars.\n\n"
    return fallback + block + "\n"


def canonical_json(dataset: dict[str, Any]) -> str:
    return json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return True


def main() -> int:
    token = os.environ.get("STAR_COLLECTOR_TOKEN", "").strip()
    if not token:
        print("STAR_COLLECTOR_TOKEN is required", file=sys.stderr)
        return 2
    try:
        existing = load_dataset()
        existing_readme = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
        updated = merge_dataset(existing, fetch_all_starred(token), utc_now())
        data_changed = atomic_write_if_changed(DATA_PATH, canonical_json(updated))
        readme_changed = atomic_write_if_changed(README_PATH, render_readme(updated, existing_readme))
    except RuntimeError as exc:
        print(f"Star Collector failed: {exc}", file=sys.stderr)
        return 1
    print(f"Synchronization complete: data_changed={data_changed}, readme_changed={readme_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
