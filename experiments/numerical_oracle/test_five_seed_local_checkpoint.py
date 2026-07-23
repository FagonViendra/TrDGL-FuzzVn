import json
import shutil
import tempfile
import unittest
from pathlib import Path

import verify_five_seed_local_checkpoint as verifier


class FiveSeedLocalCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_complete_design_but_not_paper_ready(self) -> None:
        result = verifier.verify()
        self.assertEqual((result["events"], result["seeds"]), (480, 5))
        self.assertEqual((result["eager_measured"], result["compiled_unsupported"]), (240, 240))
        self.assertEqual(result["clean_false_positives"], 0)
        self.assertEqual((result["detected_1e_5"], result["detected_1e_4"], result["detected_1e_3"]), (40, 40, 0))
        self.assertFalse(result["certified"])
        self.assertFalse(result["paper_ready"])

    def test_evidence_matrix_marks_only_eager_cells_measured_locally(self) -> None:
        matrix_path = verifier.HERE / "evidence_matrix.json"
        audit = json.loads(matrix_path.read_text(encoding="utf-8"))
        cells = audit["factorial_matrix"]
        self.assertEqual(len(cells), 16)
        for row in cells:
            expected = "validation_only" if row["mode"] == "eager" else "unsupported_validation"
            self.assertEqual(row["status"], expected)
            self.assertEqual(row["source"], "five_seed_local_checkpoint/summary.local_factorial.json")

    def test_artifact_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "checkpoint"
            shutil.copytree(verifier.DEFAULT_ROOT, copied)
            path = copied / "summary.local_factorial.json"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(verifier.VerificationError, "artifact hash mismatch"):
                verifier.verify(copied)

    def test_compiled_unsupported_cannot_be_reported_as_zero_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "checkpoint"
            shutil.copytree(verifier.DEFAULT_ROOT, copied)
            path = copied / "diagnostic_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["results"]["compiled"]["effect_estimate"] = 0
            path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            with self.assertRaisesRegex(verifier.VerificationError, "effect estimate"):
                verifier.verify(copied)


if __name__ == "__main__":
    unittest.main()
