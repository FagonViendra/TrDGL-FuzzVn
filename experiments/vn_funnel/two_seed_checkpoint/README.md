# Two-seed Vn funnel and assertion-signal triage

This checkpoint imports the immutable 960-event stream for seeds 3407 and
7711. The ordered generation-quality funnel is:

```text
raw 960 -> parseable/AST 625 -> runnable 595 -> target-valid 482
        -> oracle-bearing 89
```

All 960 records have `null` evidence for reproducibility, duplicate review,
minimization, stable/nightly testing, and promotion. The value is unknown, not
zero. No Atlas cluster or Atlas-guidance field is recorded.

Assertion failures form a separate diagnostic branch because the benchmark
defines `runnable` as exit code zero. Four parseable programs called the target,
contained a non-fake oracle, and exited with `AssertionError`. The validated
decision ledger records:

- two `torch.reshape` signals rejected as the same invalid logical-order oracle;
- one `torch.sparse.log_softmax` signal rejected because dense zero-fill is not
  a valid sparse softmax reference;
- one `torch.compile` numerical signal retained as a provisional candidate,
  pending replay on the pinned T4/PyTorch 2.11 environment.

The local compile replay is `environment_unsupported`: PyTorch 2.6 on the RTX
3050 Ti cannot run the default Inductor backend because the Windows environment
lacks Triton. This result is not counted as non-reproduction. The candidate
ledger therefore contains one pending row and zero promoted candidates.

These are two-seed diagnostic counts, not the complete five-seed campaign and
not evidence of a confirmed PyTorch bug.
