import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sync_stars  # noqa: E402


def item(repo_id, *, description="AI agent toolkit", topics=None, starred_at="2026-01-01T00:00:00Z", missing=False):
    repo = {"id": repo_id}
    if not missing:
        repo.update(
            {
                "name": f"repo-{repo_id}",
                "full_name": f"owner/repo-{repo_id}",
                "html_url": f"https://github.com/owner/repo-{repo_id}",
                "description": description,
                "language": "Python",
                "stargazers_count": repo_id,
                "topics": topics or [],
                "updated_at": "2026-01-01T00:00:00Z",
                "homepage": None,
                "owner": {"login": "owner"},
            }
        )
    return {"starred_at": starred_at, "repo": repo}


class StarCollectorTests(unittest.TestCase):
    def test_large_input_duplicate_removal_and_missing_fields(self):
        previous = sync_stars.merge_dataset(sync_stars.empty_dataset(), [item(999)], "2026-01-01T00:00:00Z")
        incoming = [item(repo_id) for repo_id in range(1, 106)]
        incoming.extend([item(42, description="AI coding agent"), item(500, missing=True)])
        result = sync_stars.merge_dataset(previous, incoming, "2026-01-02T00:00:00Z")
        by_id = {record["id"]: record for record in result["repositories"]}

        self.assertEqual(len(by_id), 107)
        self.assertFalse(by_id[999]["starred"])
        self.assertEqual(by_id[999]["unstarred_at"], "2026-01-02T00:00:00Z")
        self.assertTrue(by_id[999]["ai_relevant"])
        self.assertEqual(by_id[42]["description"], "AI coding agent")
        self.assertEqual(by_id[500]["name"], "")

    def test_all_eight_categories(self):
        examples = {
            "ai-agents": "Multi-agent AI system with autonomous agents",
            "llms-prompt-engineering": "LLM prompt engineering toolkit",
            "rag-knowledge-systems": "RAG vector database for LLM apps",
            "automation-workflows": "AI workflow automation with n8n",
            "ai-frameworks-libraries": "AI SDK and library for applications",
            "generative-ai": "Generative AI image generation with diffusion",
            "machine-learning-computer-vision": "Machine learning computer vision with PyTorch",
            "infrastructure-deployment": "MLOps model serving and local LLM deployment",
        }
        for repo_id, (expected, description) in enumerate(examples.items(), start=1):
            with self.subTest(expected=expected):
                record = sync_stars.normalize_record(item(repo_id, description=description), None, "2026-01-01T00:00:00Z")
                self.assertTrue(record["ai_relevant"])
                self.assertEqual(record["category"], expected)

    def test_non_ai_repository_is_excluded(self):
        unrelated = sync_stars.normalize_record(
            item(2, description="A collection of public weather APIs", topics=["api"]),
            None,
            "2026-01-01T00:00:00Z",
        )
        self.assertFalse(unrelated["ai_relevant"])
        self.assertEqual(unrelated["category"], "not-ai")

    def test_controlled_sync_is_byte_identical(self):
        sync_time = "2026-01-01T00:00:00Z"
        items = [item(1), item(2, description="Public API directory", topics=["api"])]
        first = sync_stars.merge_dataset(sync_stars.empty_dataset(), items, sync_time)
        second = sync_stars.merge_dataset(first, items, sync_time)

        self.assertEqual(sync_stars.canonical_json(first), sync_stars.canonical_json(second))
        existing = "# Project\n\nKeep this introduction.\n"
        self.assertEqual(sync_stars.render_readme(first, existing), sync_stars.render_readme(second, existing))
        readme = sync_stars.render_readme(first)
        self.assertNotIn("Public API directory", readme)
        self.assertIn("| Repository | Description | Stars |", readme)

    def test_readme_always_renders_eight_colored_group_titles(self):
        dataset = sync_stars.merge_dataset(sync_stars.empty_dataset(), [item(1)], "2026-01-01T00:00:00Z")
        readme = sync_stars.render_readme(dataset)

        self.assertEqual(readme.count("| Repository | Description | Stars |"), 8)
        for _, title, _ in sync_stars.CATEGORIES:
            self.assertIn(f"### {title}", readme)
        self.assertNotIn("Other AI", readme)

    def test_readme_updates_only_managed_block(self):
        dataset = sync_stars.merge_dataset(sync_stars.empty_dataset(), [item(1)], "2026-01-01T00:00:00Z")
        existing = "# My project\n\n![Banner](banner.png)\n\n<!-- STAR-COLLECTOR:START -->\nold links\n<!-- STAR-COLLECTOR:END -->\n\nFooter text.\n"
        readme = sync_stars.render_readme(dataset, existing)

        self.assertTrue(readme.startswith("# My project\n\n![Banner](banner.png)"))
        self.assertTrue(readme.endswith("Footer text.\n"))
        self.assertNotIn("old links", readme)
        self.assertIn("| [owner/repo-1](https://github.com/owner/repo-1) | AI agent toolkit | ⭐ 1 |", readme)

    def test_readme_rejects_unpaired_marker(self):
        with self.assertRaises(RuntimeError):
            sync_stars.render_readme(sync_stars.empty_dataset(), "User text\n<!-- STAR-COLLECTOR:START -->\n")


if __name__ == "__main__":
    unittest.main()
