#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const START_MARKER = "<!-- STAR-COLLECTOR:START -->";
const END_MARKER = "<!-- STAR-COLLECTOR:END -->";
const REPOSITORY_PATTERN = /^https:\/\/github\.com\/([^/\s]+\/[^/\s]+)\s+—\s+⭐\s+\*\*[^*]+\*\*/gim;

const CATEGORIES = [
  {
    id: "agents",
    heading: "## 🔵 🤖 AI Agents",
    terms: ["ai agent", "ai-agent", "ai assistant", "ai-assistant", "agent", "agents", "gui agent", "gui-agent", "agentic", "multi-agent", "autonomous agent", "agent framework", "agent platform", "computer use", "computer-use"],
  },
  {
    id: "llm-prompting",
    heading: "## 🟣 🧠 LLMs & Prompt Engineering",
    terms: ["llm", "large language model", "prompt engineering", "prompt-engineering", "prompt", "context engineering", "chatgpt", "gpt", "openai", "claude", "gemini", "ollama", "langchain", "llamaindex"],
  },
  {
    id: "rag",
    heading: "## 🟢 🔎 RAG & Knowledge Systems",
    terms: ["rag", "retrieval-augmented", "retrieval augmented", "vector database", "vector-database", "embedding", "semantic search", "knowledge base", "knowledge graph"],
  },
  {
    id: "automation",
    heading: "## 🟠 ⚙️ Automation & Workflows",
    terms: ["ai automation", "workflow automation", "automation", "workflow", "n8n", "robotic process", "rpa", "browser agent", "browser automation"],
  },
  {
    id: "frameworks",
    heading: "## 🟡 🧰 AI Frameworks & Libraries",
    terms: ["ai framework", "llm framework", "machine learning framework", "ai library", "llm library", "ai sdk", "llm sdk", "ai toolkit", "library for building ai", "orchestration framework", "pytorch", "tensorflow"],
  },
  {
    id: "generative",
    heading: "## 🔴 🎨 Generative AI (Image, Video, Audio, 3D)",
    terms: ["generative ai", "image generation", "video generation", "audio generation", "music generation", "text-to-image", "text to image", "text-to-video", "stable diffusion", "diffusion model", "speech synthesis", "text-to-speech", "3d generation"],
  },
  {
    id: "ml-cv",
    heading: "## 🟤 👁️ Machine Learning & Computer Vision",
    terms: ["machine learning", "machine-learning", "deep learning", "deep-learning", "computer vision", "computer-vision", "object detection", "image classification", "neural network", "natural language processing", "nlp"],
  },
  {
    id: "infrastructure",
    heading: "## ⚫ 🚀 Infrastructure & Deployment (MCP, APIs, MLOps, Local AI, Serving)",
    terms: ["model context protocol", "model-context-protocol", "mcp", "mcp server", "mcp-server", "mlops", "llmops", "model serving", "model performance", "ai model", "inference server", "inference engine", "model optimization", "network quantization", "network compression", "local ai", "local-ai", "self-hosted ai", "ai infrastructure", "llm api", "ai api"],
  },
];

const AI_TERMS = [
  "ai",
  "artificial intelligence",
  "artificial-intelligence",
  "automation",
  "agent",
  "agents",
  "agentic",
  "ai agent",
  "ai-agent",
  "ai assistant",
  "ai-assistant",
  "generative ai",
  "generative-ai",
  "machine learning",
  "machine-learning",
  "deep learning",
  "deep-learning",
  "computer vision",
  "computer-vision",
  "large language model",
  "large-language-model",
  "llm",
  "prompt engineering",
  "prompt-engineering",
  "retrieval augmented",
  "retrieval-augmented",
  "rag",
  "stable diffusion",
  "diffusion",
  "natural language processing",
  "nlp",
  "model context protocol",
  "model-context-protocol",
  "mcp",
  "mlops",
  "llmops",
  "neural network",
  "transformer",
  "embedding",
  "openai",
  "chatgpt",
  "claude",
  "gemini",
  "ollama",
  "langchain",
  "llamaindex",
  "pytorch",
  "tensorflow",
  "computer use",
  "computer-use",
];

function searchableText(repo) {
  return [repo.name, repo.full_name, repo.description, ...(repo.topics || [])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function includesTerm(text, term) {
  if (/^[a-z0-9]+$/i.test(term)) {
    return new RegExp(`(^|[^a-z0-9])${term}([^a-z0-9]|$)`, "i").test(text);
  }
  return text.includes(term);
}

function isAiRepository(repo) {
  const text = searchableText(repo);
  const topics = new Set((repo.topics || []).map((topic) => topic.toLowerCase()));
  return topics.has("ai") || topics.has("artificial-intelligence") || AI_TERMS.some((term) => includesTerm(text, term));
}

function classifyRepository(repo) {
  const text = searchableText(repo);
  let best = null;

  for (const category of CATEGORIES) {
    const score = category.terms.reduce((total, term) => total + (includesTerm(text, term) ? 1 : 0), 0);
    if (score > 0 && (!best || score > best.score)) {
      best = { id: category.id, score };
    }
  }

  return best?.id || "frameworks";
}

function formatStars(count) {
  if (count < 1000) return String(count);
  const value = count / 1000;
  return `${value >= 100 ? Math.round(value) : value.toFixed(1).replace(/\.0$/, "")}k`;
}

function sanitizeDescription(description) {
  const singleLine = (description || "No description provided.").replace(/\s+/g, " ").trim();
  return singleLine
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/!\[/g, "!\\[")
    .replace(/^([#>*+-])/, "\\$1");
}

function formatRepository(repo) {
  return `${repo.html_url} — ⭐ **${formatStars(repo.stargazers_count)}**  \n${sanitizeDescription(repo.description)}`;
}

function readExistingAssignments(readme) {
  const assignments = new Map();

  for (let index = 0; index < CATEGORIES.length; index += 1) {
    const category = CATEGORIES[index];
    const start = readme.indexOf(category.heading);
    if (start === -1) continue;

    const nextStarts = CATEGORIES.slice(index + 1)
      .map((candidate) => readme.indexOf(candidate.heading, start + category.heading.length))
      .filter((position) => position !== -1);
    const end = nextStarts.length ? Math.min(...nextStarts) : readme.indexOf(END_MARKER, start);
    const section = readme.slice(start, end === -1 ? undefined : end);

    for (const match of section.matchAll(REPOSITORY_PATTERN)) {
      assignments.set(match[1].toLowerCase(), category.id);
    }
  }

  return assignments;
}

function replaceCategoryContents(readme, category, repositories) {
  const headingStart = readme.indexOf(category.heading);
  if (headingStart === -1) throw new Error(`Missing README heading: ${category.heading}`);

  const bodyStart = headingStart + category.heading.length;
  const divider = "![Immagine](RubyDivisorR.png)";
  let bodyEnd = readme.indexOf(divider, bodyStart);
  if (bodyEnd === -1) bodyEnd = readme.indexOf("![Immagine](FinalRuby.png)", bodyStart);
  if (bodyEnd === -1) throw new Error(`Missing divider after README heading: ${category.heading}`);

  const entries = repositories.map(formatRepository).join("\n\n");
  const body = entries ? `\n\n${entries}\n\n` : "\n\n";
  return `${readme.slice(0, bodyStart)}${body}${readme.slice(bodyEnd)}`;
}

function updateReadme(readme, starredRepos, accountRepository) {
  if (!readme.includes(START_MARKER) || !readme.includes(END_MARKER)) {
    throw new Error("README is missing STAR-COLLECTOR markers; refusing to modify it.");
  }

  const existingAssignments = readExistingAssignments(readme);
  const grouped = new Map(CATEGORIES.map((category) => [category.id, []]));

  for (const repo of starredRepos) {
    if (repo.private || repo.archived || repo.full_name.toLowerCase() === accountRepository.toLowerCase()) continue;
    const currentCategory = existingAssignments.get(repo.full_name.toLowerCase());
    if (!currentCategory && !isAiRepository(repo)) continue;
    grouped.get(currentCategory || classifyRepository(repo)).push(repo);
  }

  for (const repositories of grouped.values()) {
    repositories.sort((left, right) => left.full_name.localeCompare(right.full_name, "en", { sensitivity: "base" }));
  }

  let updated = readme;
  for (const category of CATEGORIES) {
    updated = replaceCategoryContents(updated, category, grouped.get(category.id));
  }
  return updated;
}

async function fetchStarredRepositories(username, token) {
  const repositories = [];
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "awesome-ai-star-collector",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  for (let page = 1; ; page += 1) {
    const response = await fetch(`https://api.github.com/users/${encodeURIComponent(username)}/starred?per_page=100&page=${page}`, { headers });
    if (!response.ok) throw new Error(`GitHub starred repositories request failed: ${response.status} ${await response.text()}`);
    const batch = await response.json();
    repositories.push(...batch);
    if (batch.length < 100) break;
  }

  return repositories;
}

async function main() {
  const token = process.env.GITHUB_TOKEN;
  const username = process.env.STARRED_USERNAME;
  const repository = process.env.GITHUB_REPOSITORY;
  const readmePath = path.resolve(process.env.README_PATH || "README.md");

  if (!username || !repository) {
    throw new Error("STARRED_USERNAME and GITHUB_REPOSITORY are required.");
  }

  const readme = fs.readFileSync(readmePath, "utf8");
  const starredRepos = await fetchStarredRepositories(username, token);
  const updated = updateReadme(readme, starredRepos, repository);

  if (updated !== readme) fs.writeFileSync(readmePath, updated);
  console.log(`Processed ${starredRepos.length} starred repositories; README ${updated === readme ? "unchanged" : "updated"}.`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { AI_TERMS, CATEGORIES, classifyRepository, fetchStarredRepositories, formatStars, isAiRepository, readExistingAssignments, updateReadme };
