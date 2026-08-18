#!/usr/bin/env python3
"""Synchronize and organize the authenticated user's GitHub stars."""

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

# Order is also the deterministic display order. The colored circle and subject
# icon keep group headings scannable in both light and dark GitHub themes.
CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ai-agents",
        "🔵 🤖 AI Agents",
        (
            "ai agent", "ai agents", "agentic", "autonomous agent",
            "multi agent", "multiagent", "computer use", "browser use",
            "crewai", "autogen", "swarm", "agent framework",
        ),
    ),
    (
        "llms-prompt-engineering",
        "🟣 🧠 LLMs & Prompt Engineering",
        (
            "llm", "large language model", "language model", "prompt engineering",
            "prompting", "prompt template", "transformer", "fine tuning", "finetuning",
            "instruction tuning", "gpt", "claude", "gemini", "deepseek", "qwen",
        ),
    ),
    (
        "rag-knowledge-systems",
        "🟢 🔎 RAG & Knowledge Systems",
        (
            "rag", "retrieval augmented", "retrieval", "vector database",
            "vector store", "embedding", "semantic search", "knowledge base",
            "knowledge graph", "document qa", "graph rag", "graphrag",
        ),
    ),
    (
        "automation-workflows",
        "🟠 ⚙️ Automation & Workflows",
        (
            "ai automation", "workflow automation", "automation", "workflow",
            "workflows", "n8n", "activepieces", "rpa", "robotic process automation",
            "low code", "no code", "computer automation", "browser automation",
        ),
    ),
    (
        "ai-frameworks-libraries",
        "🟡 🧰 AI Frameworks & Libraries",
        (
            "ai framework", "ai library", "ai sdk", "llm framework", "llm library",
            "agent toolkit", "ai toolkit", "langchain", "llamaindex", "semantic kernel",
            "pydantic ai", "dspy", "instructor", "haystack",
        ),
    ),
    (
        "generative-ai",
        "🔴 🎨 Generative AI (Image, Video, Audio, 3D)",
        (
            "generative ai", "image generation", "video generation", "audio generation",
            "music generation", "3d generation", "text to image", "text to video",
            "text to speech", "speech synthesis", "voice cloning", "diffusion",
            "stable diffusion", "comfyui", "automatic1111", "midjourney",
        ),
    ),
    (
        "machine-learning-computer-vision",
        "🟤 👁️ Machine Learning & Computer Vision",
        (
            "machine learning", "deep learning", "computer vision", "neural network",
            "pytorch", "tensorflow", "scikit learn", "object detection", "segmentation",
            "image classification", "opencv", "yolo", "vision model", "data science",
        ),
    ),
    (
        "infrastructure-deployment",
        "⚫ 🚀 Infrastructure & Deployment (MCP, APIs, MLOps, Local AI, Serving)",
        (
            "model context protocol", "mcp server", "mcp", "mlops", "model serving",
            "inference server", "inference engine", "local ai", "local llm", "ai api",
            "llm api", "ai gateway", "llm gateway", "openai proxy", "gpu",
            "vllm", "ollama", "llama cpp", "deployment", "serving",
        ),
    ),
)
UNCATEGORIZED = ("not-ai", "Not AI")

AI_SIGNALS = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "ai agent", "ai agents", "agentic ai", "llm",
    "large language model", "language model", "generative ai", "chatbot",
    "openai", "anthropic", "claude", "gemini", "deepseek", "mistral", "qwen",
    "hugging face", "transformer", "rag", "retrieval augmented", "embedding",
    "vector database", "computer vision", "diffusion", "text to image",
    "speech recognition", "model context protocol", "mcp", "prompt engineering",
    "copilot", "codex", "pytorch", "tensorflow", "stable diffusion",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_dataset() -> dict[str, Any]:
    return {"schema_version": 2, "last_sync": None, "repositories": []}


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


def searchable_text(record: dict[str, Any]) -> str:
    values = [
        record.get("name"), record.get("full_name"), record.get("description"),
        record.get("homepage"), " ".join(record.get("topics") or []),
    ]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()) for value in values if value)


def has_phrase(text: str, phrase: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
    return bool(normalized and re.search(rf"(?:^|\s){re.escape(normalized)}(?:\s|$)", text))


def classify_ai(record: dict[str, Any]) -> tuple[bool, str, str]:
    text = searchable_text(record)
    if not any(has_phrase(text, signal) for signal in AI_SIGNALS):
        return False, UNCATEGORIZED[0], UNCATEGORIZED[1]

    scores = [
        (sum(1 for keyword in keywords if has_phrase(text, keyword)), -position, key, title)
        for position, (key, title, keywords) in enumerate(CATEGORIES)
    ]
    score, _, key, title = max(scores)
    if score == 0:
        # Explicitly AI-related repositories without a narrower signal belong to
        # the broad frameworks/libraries group instead of an unlisted catch-all.
        key, title, _ = CATEGORIES[4]
    return True, key, title


def normalize_record(item: dict[str, Any], existing: dict[str, Any] | None, sync_time: str) -> dict[str, Any]:
    repo = item["repo"]
    owner = repo.get("owner") if isinstance(repo.get("owner"), dict) else {}
    repo_id = int(repo["id"])
    starred_at = item.get("starred_at") or (existing or {}).get("starred_at") or sync_time

    def field(name: str, default: Any = None) -> Any:
        if name in repo:
            return repo[name]
        return (existing or {}).get(name, default)

    record = {
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
    relevant, category, category_title = classify_ai(record)
    record.update(ai_relevant=relevant, category=category, category_title=category_title)
    return record


def merge_dataset(existing_data: dict[str, Any], starred_items: list[dict[str, Any]], sync_time: str) -> dict[str, Any]:
    existing_by_id = {
        int(record["id"]): record for record in existing_data.get("repositories", [])
        if isinstance(record, dict) and record.get("id") is not None
    }
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
        relevant, category, category_title = classify_ai(historical)
        historical.update(ai_relevant=relevant, category=category, category_title=category_title)
        if historical.get("starred", True):
            historical["starred"] = False
            historical["unstarred_at"] = historical.get("unstarred_at") or sync_time
        merged.append(historical)
    merged.extend(current_by_id.values())
    merged.sort(key=lambda record: int(record["id"]))

    old_repositories = existing_data.get("repositories", [])
    changed = merged != old_repositories or existing_data.get("schema_version") != 2 or existing_data.get("last_sync") is None
    return {
        "schema_version": 2,
        "last_sync": sync_time if changed else existing_data.get("last_sync"),
        "repositories": merged,
    }


def markdown_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text.replace("\\", "\\\\").replace("|", "\\|")


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


def render_managed_block(dataset: dict[str, Any]) -> str:
    active = [
        record for record in dataset["repositories"]
        if record.get("starred") and record.get("ai_relevant")
    ]
    active.sort(
        key=lambda record: (record.get("starred_at") or "", record.get("full_name") or ""),
        reverse=True,
    )
    lines = [START_MARKER, "## 📚 AI Repository Collection", ""]
    for key, title, _ in CATEGORIES:
        records = [record for record in active if record.get("category") == key]
        lines.extend([
            f"### {title}", "", "| Repository | Description | Stars |", "|---|---|---:|",
        ])
        for record in records:
            name = str(record.get("full_name") or record.get("name") or record.get("id") or "Repository")
            name = name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            url = str(record.get("html_url") or "").strip()
            if url:
                description = markdown_cell(record.get("description")) or "No description available."
                lines.append(f"| [{name}]({url}) | {description} | ⭐ {short_stars(record.get('stargazers_count'))} |")
        lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def render_readme(dataset: dict[str, Any], existing_readme: str = "") -> str:
    block = render_managed_block(dataset)
    has_start = START_MARKER in existing_readme
    has_end = END_MARKER in existing_readme
    if has_start != has_end:
        raise RuntimeError("README has only one Star Collector marker; refusing to overwrite user content")
    if has_start:
        start = existing_readme.index(START_MARKER)
        end = existing_readme.index(END_MARKER, start) + len(END_MARKER)
        return (existing_readme[:start] + block + existing_readme[end:]).rstrip() + "\n"
    if existing_readme.strip():
        return existing_readme.rstrip() + "\n\n" + block + "\n"
    return block + "\n"


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
    visible = sum(1 for record in updated["repositories"] if record.get("starred") and record.get("ai_relevant"))
    print(f"Synchronization complete: ai_repositories={visible}, data_changed={data_changed}, readme_changed={readme_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
