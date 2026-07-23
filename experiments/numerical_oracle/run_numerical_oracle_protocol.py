"""Run a matched CPU/CUDA, eager/compiled, forward/gradient oracle matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


SCHEMA_VERSION = "trdgl_numerical_oracle_event_v2"
EVENT_ID_FIELDS = (
    "run_id", "evidence_label", "case_id", "seed", "device", "execution_mode",
    "execution_backend", "check_kind", "input_dtype", "reference_dtype",
    "control_kind", "injected_delta", "tolerance_kind", "atol", "rtol",
    "certified_bound", "certified_bound_source_sha256",
)


def function(x: torch.Tensor) -> torch.Tensor:
    return torch.sin(x) * torch.exp(-0.1 * x.square()) + 0.01 * x.square()


def ulp_max(actual: torch.Tensor, reference: torch.Tensor, dtype: torch.dtype) -> int:
    a = actual.detach().cpu().to(dtype).contiguous().numpy()
    b = reference.detach().cpu().to(dtype).contiguous().numpy()
    if dtype == torch.float32:
        unsigned, sign = np.uint32, np.uint32(0x80000000)
    elif dtype == torch.float64:
        unsigned, sign = np.uint64, np.uint64(0x8000000000000000)
    else:
        raise ValueError(dtype)
    ai = a.view(unsigned)
    bi = b.view(unsigned)
    ao = np.where((ai & sign) != 0, ~ai, ai | sign)
    bo = np.where((bi & sign) != 0, ~bi, bi | sign)
    diff = np.maximum(ao, bo) - np.minimum(ao, bo)
    return int(diff.max(initial=0))


def environment() -> dict[str, Any]:
    try:
        driver = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.splitlines()[0].strip()
    except (FileNotFoundError, subprocess.SubprocessError, IndexError):
        driver = None
    return {
        "platform": platform.platform(),
        "cpu": platform.processor() or None,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "driver_version": driver,
        "deterministic_algorithms": bool(torch.are_deterministic_algorithms_enabled()),
    }


def event_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: payload[key] for key in EVENT_ID_FIELDS}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def compiled_exception_status(message: str) -> str:
    return "unsupported" if "not supported" in message.lower() or platform.system() == "Windows" else "error"


def compiled_preflight(compiled_function: Any, device: str) -> dict[str, Any]:
    """Probe a compiled backend once per device instead of once per threshold cell."""
    if device == "cuda" and not torch.cuda.is_available():
        return {"status": "unsupported", "error": "CUDA is not available"}
    if compiled_function is None:
        return {"status": "unsupported", "error": "torch.compile is not available"}
    try:
        probe = torch.linspace(-1.0, 1.0, 8, device=device, dtype=torch.float32)
        result = compiled_function(probe)
        if device == "cuda":
            torch.cuda.synchronize()
        if result.shape != probe.shape or not bool(torch.isfinite(result).all().item()):
            raise RuntimeError("compiled preflight returned an invalid tensor")
        return {"status": "supported", "error": None}
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:2000]
        return {"status": compiled_exception_status(message), "error": message}


def measure(
    *, run_id: str, evidence_label: str, seed: int, device: str, mode: str,
    check_kind: str, dtype_name: str, control_kind: str, tolerance_kind: str,
    tolerance: float | None, certified_bound: float | None,
    certified_bound_source_sha256: str | None,
    inject_delta: float, compiled_function: Any, compiled_probe: dict[str, Any] | None,
    env: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "evidence_label": evidence_label,
        "case_id": "analytic_elementwise_v1",
        "seed": seed,
        "device": device,
        "execution_mode": mode,
        "execution_backend": "torch.compile_inductor" if mode == "compiled" else "torch_eager",
        "check_kind": check_kind,
        "input_dtype": dtype_name,
        "reference_dtype": "float64",
        "control_kind": control_kind,
        "injected_delta": inject_delta if control_kind == "injected" else None,
        "tolerance_kind": tolerance_kind,
        "atol": tolerance if tolerance_kind == "fixed" else None,
        "rtol": tolerance if tolerance_kind == "fixed" else None,
        "certified_bound": certified_bound if tolerance_kind == "certified" else None,
        "certified_bound_source_sha256": (
            certified_bound_source_sha256 if tolerance_kind == "certified" else None
        ),
        "status": "pending",
        "abs_error_max": None,
        "rel_error_max": None,
        "ulp_error_max": None,
        "duration_seconds": None,
        "environment": env,
        "error": None,
    }
    base["event_id"] = event_id(base)
    started = time.perf_counter()
    if device == "cuda" and not torch.cuda.is_available():
        base.update(status="unsupported", duration_seconds=time.perf_counter() - started, error="CUDA is not available")
        return base
    if mode == "compiled" and not hasattr(torch, "compile"):
        base.update(status="unsupported", duration_seconds=time.perf_counter() - started, error="torch.compile is not available")
        return base
    if mode == "compiled" and compiled_probe is not None and compiled_probe["status"] != "supported":
        base.update(
            status=compiled_probe["status"],
            duration_seconds=time.perf_counter() - started,
            error=f"compiled preflight: {compiled_probe['error']}",
        )
        return base

    dtype = {"float32": torch.float32, "float64": torch.float64}[dtype_name]
    try:
        generator = torch.Generator(device="cpu").manual_seed(seed)
        reference_input = torch.randn(64, generator=generator, dtype=torch.float64, requires_grad=True)
        reference_output = function(reference_input)
        if check_kind == "gradient":
            reference_value = torch.autograd.grad(reference_output.sum(), reference_input)[0]
        else:
            reference_value = reference_output

        target_input = reference_input.detach().to(device=device, dtype=dtype).requires_grad_(check_kind == "gradient")
        target_function = compiled_function if mode == "compiled" else function
        target_output = target_function(target_input)
        if check_kind == "gradient":
            target_value = torch.autograd.grad(target_output.sum(), target_input)[0]
        else:
            target_value = target_output
        if control_kind == "injected":
            target_value = target_value + inject_delta
        actual64 = target_value.detach().cpu().to(torch.float64)
        reference64 = reference_value.detach().cpu()
        difference = (actual64 - reference64).abs()
        absolute = float(difference.max().item())
        relative = float((difference / reference64.abs().clamp_min(torch.finfo(torch.float64).tiny)).max().item())
        if tolerance_kind == "fixed":
            assert tolerance is not None
            allowed = tolerance + tolerance * reference64.abs()
        else:
            assert certified_bound is not None
            allowed = torch.full_like(reference64, certified_bound)
        passed = bool(torch.all(difference <= allowed).item())
        base.update(
            status="pass" if passed else "fail",
            abs_error_max=absolute,
            rel_error_max=relative,
            ulp_error_max=ulp_max(target_value, reference_value, dtype),
            duration_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        status = compiled_exception_status(message) if mode == "compiled" else "error"
        base.update(status=status, duration_seconds=time.perf_counter() - started, error=message[:2000])
    return base


def comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, help="Optional immutable run/environment manifest")
    parser.add_argument("--evidence-label", choices=("local_validation", "campaign"), default="local_validation")
    parser.add_argument("--seeds", default="3407,7711,12011,19001,27103")
    parser.add_argument("--devices", default="cpu,cuda")
    parser.add_argument("--modes", default="eager,compiled")
    parser.add_argument("--checks", default="forward,gradient")
    parser.add_argument("--dtypes", default="float32,float64")
    parser.add_argument("--tolerances", default="1e-3,1e-4,1e-5")
    parser.add_argument("--include-injected", action="store_true")
    parser.add_argument("--inject-delta", type=float, default=2e-4)
    parser.add_argument("--certified-bound", type=float, help="Externally justified absolute bound; omitted by default and never inferred")
    parser.add_argument(
        "--certified-bound-source", type=Path,
        help="Certificate/theorem artifact whose SHA-256 justifies --certified-bound",
    )
    args = parser.parse_args()

    seeds = [int(value) for value in comma_list(args.seeds)]
    devices = comma_list(args.devices)
    modes = comma_list(args.modes)
    checks = comma_list(args.checks)
    dtypes = comma_list(args.dtypes)
    tolerances = [float(value) for value in comma_list(args.tolerances)]
    for value, allowed, label in ((devices, {"cpu", "cuda"}, "device"), (modes, {"eager", "compiled"}, "mode"), (checks, {"forward", "gradient"}, "check"), (dtypes, {"float32", "float64"}, "dtype")):
        invalid = set(value) - allowed
        if invalid:
            raise SystemExit(f"invalid {label}: {sorted(invalid)}")
    if not tolerances or any(value < 0 for value in tolerances):
        raise SystemExit("tolerances must be non-negative")
    if args.certified_bound is not None and args.certified_bound < 0:
        raise SystemExit("certified bound must be non-negative")
    if (args.certified_bound is None) != (args.certified_bound_source is None):
        raise SystemExit("--certified-bound and --certified-bound-source must be supplied together")
    if args.certified_bound_source is not None and not args.certified_bound_source.is_file():
        raise SystemExit(f"certified bound source not found: {args.certified_bound_source}")
    certified_source_sha256 = (
        hashlib.sha256(args.certified_bound_source.read_bytes()).hexdigest()
        if args.certified_bound_source is not None else None
    )

    started_utc = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    run_id = f"numerical-oracle-{started_utc.strftime('%Y%m%dT%H%M%SZ')}"
    env = environment()
    compiled_function = torch.compile(function, backend="inductor", fullgraph=True) if "compiled" in modes and hasattr(torch, "compile") else None
    compiled_probes = {
        device: compiled_preflight(compiled_function, device)
        for device in devices
    } if "compiled" in modes else {}
    env["compiled_preflight"] = compiled_probes
    controls = ["clean", "injected"] if args.include_injected else ["clean"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    status_counts: Counter[str] = Counter()
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for seed in seeds:
            for device in devices:
                for mode in modes:
                    for check in checks:
                        for dtype in dtypes:
                            for control in controls:
                                tolerance_specs = [("fixed", tolerance, None) for tolerance in tolerances]
                                if args.certified_bound is not None:
                                    tolerance_specs.append(("certified", None, args.certified_bound))
                                for tolerance_kind, tolerance, certified_bound in tolerance_specs:
                                    row = measure(
                                        run_id=run_id, evidence_label=args.evidence_label, seed=seed,
                                        device=device, mode=mode, check_kind=check, dtype_name=dtype,
                                        control_kind=control, tolerance_kind=tolerance_kind,
                                        tolerance=tolerance, certified_bound=certified_bound,
                                        certified_bound_source_sha256=certified_source_sha256,
                                        inject_delta=args.inject_delta, compiled_function=compiled_function,
                                        compiled_probe=compiled_probes.get(device), env=env,
                                    )
                                    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                                    handle.flush()
                                    count += 1
                                    status_counts[row["status"]] += 1
    completed_utc = datetime.now(timezone.utc)
    wall_seconds = time.perf_counter() - started_clock
    manifest_path = args.run_manifest
    if manifest_path is not None:
        manifest = {
            "schema_version": "trdgl_numerical_oracle_run_v1",
            "run_id": run_id,
            "evidence_label": args.evidence_label,
            "started_utc": started_utc.isoformat(),
            "completed_utc": completed_utc.isoformat(),
            "wall_seconds": wall_seconds,
            "events": count,
            "events_per_second": count / wall_seconds if wall_seconds else None,
            "status_counts": dict(sorted(status_counts.items())),
            "design": {
                "seeds": seeds,
                "devices": devices,
                "modes": modes,
                "checks": checks,
                "dtypes": dtypes,
                "fixed_tolerances": tolerances,
                "controls": controls,
                "inject_delta": args.inject_delta,
                "certified_bound": args.certified_bound,
                "certified_bound_source": str(args.certified_bound_source) if args.certified_bound_source else None,
                "certified_bound_source_sha256": certified_source_sha256,
            },
            "environment": env,
            "protocol_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "events_path": str(args.output),
            "events_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({
        "run_id": run_id,
        "events": count,
        "wall_seconds": round(wall_seconds, 6),
        "events_per_second": round(count / wall_seconds, 3) if wall_seconds else None,
        "output": str(args.output),
        "run_manifest": str(manifest_path) if manifest_path else None,
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
