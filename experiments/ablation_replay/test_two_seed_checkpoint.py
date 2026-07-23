import json
import shutil
import tempfile
import unittest
from pathlib import Path

import verify_two_seed_checkpoint as verifier


class TwoSeedAblationCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_valid_but_not_paper_ready(self) -> None:
        result = verifier.verify()
        self.assertEqual(result["result"], "pass")
        self.assertEqual((result["seeds"], result["b3_events"], result["decisions"]), (2, 240, 1200))
        self.assertEqual((result["ast_delta"], result["oracle_bypass_delta"]), (0, 1))
        self.assertIsNone(result["vn_effect"])
        self.assertIsNone(result["atlas_effect"])
        self.assertFalse(result["paper_ready"])

    def test_artifact_hash_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "checkpoint"
            shutil.copytree(verifier.DEFAULT_CHECKPOINT, copied)
            path = copied / "ablation_summary.csv"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "artifact hash mismatch"):
                verifier.verify(copied)

    def test_null_vn_effect_cannot_be_rewritten_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "checkpoint"
            shutil.copytree(verifier.DEFAULT_CHECKPOINT, copied)
            path = copied / "ablation_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["component_effects"]["verified_novelty_gate"]["effectiveness_estimate"] = 0
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "Vn unavailable effect"):
                verifier.verify(copied)

    def test_canonical_json_source_hash_is_eol_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lf = root / "lf.json"
            crlf = root / "crlf.json"
            lf.write_bytes(b'{\n  "seed": 3407,\n  "complete": true\n}\n')
            crlf.write_bytes(b'{\r\n  "seed": 3407,\r\n  "complete": true\r\n}\r\n')
            self.assertEqual(
                verifier.source_digest(lf, "canonical_json_utf8"),
                verifier.source_digest(crlf, "canonical_json_utf8"),
            )


if __name__ == "__main__":
    unittest.main()
