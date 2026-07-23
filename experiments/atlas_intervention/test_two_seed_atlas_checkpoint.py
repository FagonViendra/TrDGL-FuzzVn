import unittest

import verify_two_seed_atlas_checkpoint as verifier


class TwoSeedAtlasCheckpointTests(unittest.TestCase):
    def test_checkpoint_fails_closed_with_null_effectiveness(self) -> None:
        result = verifier.verify()
        self.assertEqual(result["result"], "pass")
        self.assertFalse(result["raw_atlas"])
        self.assertFalse(result["independent_manifest"])
        self.assertEqual(result["provisional_candidates"], 1)
        self.assertEqual((result["duplicate_pairs"], result["planning_pairs"]), (0, 0))
        self.assertIsNone(result["effectiveness_metrics"])
        self.assertFalse(result["paper_ready"])


if __name__ == "__main__":
    unittest.main()
