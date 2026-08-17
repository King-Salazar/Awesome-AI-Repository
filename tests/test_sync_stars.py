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

    def test_ai_filter_and_categories(self):
        ai = sync_stars.normalize_record(item(1, description="RAG vector database for LLM apps"), None, "2026-01-01T00:00:00Z")
        unrelated = sync_stars.normalize_record(item(2, description="A collection of public weather APIs", topics=["api"]), None, "2026-01-01T00:00:00Z")

        self.assertTrue(ai["ai_relevant"])
        self.assertEqual(ai["category"], "rag")
        self.assertFalse(unrelated["ai_relevant"])

    def test_controlled_sync_is_byte_identical(self):
        sync_time = "2026-01-01T00:00:00Z"
        items = [item(1), item(2, description="Public API directory", topics=["api"])]
        first = sync_stars.merge_dataset(sync_stars.empty_dataset(), items, sync_time)
        second = sync_stars.merge_dataset(first, items, sync_time)

        self.assertEqual(sync_stars.canonical_json(first), sync_stars.canonical_json(second))
        self.assertEqual(sync_stars.render_readme(first), sync_stars.render_readme(second))
        readme = sync_stars.render_readme(first)
        self.assertIn("AI Agents & Automation", readme)
        self.assertNotIn("Public API directory", readme)


if __name__ == "__main__":
    unittest.main()
