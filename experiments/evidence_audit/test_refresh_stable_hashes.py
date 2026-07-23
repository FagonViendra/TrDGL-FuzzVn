from __future__ import annotations

import unittest
from unittest.mock import patch

import refresh_stable_hashes as refresh
import validate_requirements_matrix as validator


class StableHashRefreshTests(unittest.TestCase):
    def test_machine_readable_campaign_matches_evidence_facts(self) -> None:
        import json

        matrix = json.loads(validator.MATRIX.read_text(encoding="utf-8"))
        result = validator.validate_semantic_sources(matrix)
        self.assertEqual(result["campaign_observed_events"], 960)
        self.assertEqual(
            result["baseline_counts"],
            {"B0": 240, "B1": 240, "B2": 240, "B3": 240},
        )
        self.assertEqual(result["audited_shard_transcript_events"], 480)
        self.assertEqual(result["persisted_evidence_ceiling"], 960)
        self.assertEqual(result["complete_seed_shards"], 2)
        self.assertEqual(result["paired_prompts"], 240)
        self.assertEqual(result["vn_oracle_bearing"], 89)
        self.assertEqual(result["ablation_b3_events"], 240)
        self.assertEqual(result["numerical_events"], 480)

    def test_dirty_paper_refuses_refresh(self) -> None:
        with patch.object(refresh, "git", side_effect=["main.tex", " M TrDGL-FuzzVn_paper/main.tex"]):
            with self.assertRaisesRegex(SystemExit, "main.tex has uncommitted changes"):
                refresh.require_stable_paper()

    def test_clean_paper_returns_head(self) -> None:
        with patch.object(refresh, "git", side_effect=["main.tex", "", "abc123"]):
            self.assertEqual(refresh.require_stable_paper(), "abc123")


if __name__ == "__main__":
    unittest.main()
