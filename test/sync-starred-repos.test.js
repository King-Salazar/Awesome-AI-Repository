const test = require("node:test");
const assert = require("node:assert/strict");

const {
  CATEGORIES,
  classifyRepository,
  formatStars,
  isAiRepository,
  updateReadme,
} = require("../scripts/sync-starred-repos");

function repo(fullName, description, stars = 1234, topics = []) {
  return {
    name: fullName.split("/")[1],
    full_name: fullName,
    html_url: `https://github.com/${fullName}`,
    description,
    stargazers_count: stars,
    topics,
    private: false,
    archived: false,
  };
}

function fixtureReadme() {
  const sections = CATEGORIES.map((category, index) => {
    const existing = index === 0
      ? "\n\nhttps://github.com/example/existing — ⭐ **1**  \nExisting AI framework"
      : "";
    const divider = index === CATEGORIES.length - 1 ? "![Immagine](FinalRuby.png)" : "![Immagine](RubyDivisorR.png)";
    return `${category.heading}${existing}\n\n${divider}`;
  }).join("\n\n");

  return `![Immagine](Ruby.png)\n\n<!-- STAR-COLLECTOR:START -->\n\n# Collection\n\n${sections}\n\n## Keywords\n\nAI\n\n<!-- STAR-COLLECTOR:END -->\n`;
}

test("formats GitHub star counts consistently", () => {
  assert.equal(formatStars(318), "318");
  assert.equal(formatStars(7000), "7k");
  assert.equal(formatStars(10600), "10.6k");
  assert.equal(formatStars(88700), "88.7k");
  assert.equal(formatStars(101200), "101k");
});

test("detects AI repositories and categorizes new entries", () => {
  const rag = repo("example/rag", "Retrieval-Augmented Generation with a vector database");
  const automation = repo("example/flows", "n8n AI workflow automation", 100, ["artificial-intelligence"]);
  assert.equal(isAiRepository(rag), true);
  assert.equal(isAiRepository(repo("example/plain", "A CSS color palette")), false);
  assert.equal(classifyRepository(rag), "rag");
  assert.equal(classifyRepository(automation), "automation");
});

test("updates only repository bodies and honors existing assignments", () => {
  const readme = fixtureReadme();
  const starred = [
    repo("example/existing", "<img src=x> Updated framework description", 2500),
    repo("example/new-rag", "RAG and semantic search toolkit", 9876),
    repo("example/not-ai", "A CSS color palette", 500),
  ];

  const updated = updateReadme(readme, starred, "owner/collection");

  assert.match(updated, /https:\/\/github\.com\/example\/existing — ⭐ \*\*2\.5k\*\*/);
  assert.match(updated, /&lt;img src=x&gt; Updated framework description/);
  assert.ok(updated.indexOf("example/existing") < updated.indexOf(CATEGORIES[1].heading));
  assert.ok(updated.indexOf("example/new-rag") > updated.indexOf(CATEGORIES[2].heading));
  assert.doesNotMatch(updated, /example\/not-ai/);
  assert.equal((updated.match(/!\[Immagine\]\(RubyDivisorR\.png\)/g) || []).length, 7);
  assert.match(updated, /^!\[Immagine\]\(Ruby\.png\)/);
  assert.match(updated, /## Keywords\n\nAI/);
});

test("removes an existing repository after its star is removed", () => {
  const updated = updateReadme(fixtureReadme(), [], "owner/collection");
  assert.doesNotMatch(updated, /example\/existing/);
});

test("refuses to edit a README without safety markers", () => {
  assert.throws(() => updateReadme("# README", [], "owner/collection"), /missing STAR-COLLECTOR markers/);
});
