#!/usr/bin/env python3
"""Tri-state failure-mode analysis for TrDGL-FuzzVn generation ledgers.

The analyzer is deliberately standard-library-only.  It never executes model
output: dynamic classifications use the subprocess evidence already recorded
by the benchmark harness, while static classifications use Python's AST.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "trdgl_generation_error_analysis_v20"
# A long-running refresher compares this loaded-code identity with the source
# on disk and reloads in place before producing another manifest.
LOADED_ANALYZER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
EXPECTED_BASELINES = ("B0", "B1", "B2", "B3")

# Positive means that the failure mode is present.  None means that the
# available evidence cannot distinguish present from absent.
CATEGORIES = (
    "syntax_error",
    "wrong_or_missing_target_api",
    "missing_import",
    "shape_or_dtype_error",
    "index_or_bounds_error",
    "undefined_name_error",
    "argument_signature_error",
    "dependency_import_error",
    "setup_or_environment_error",
    "resource_exhaustion",
    "runtime_error_other",
    "assertion_failure",
    "timeout",
    "missing_oracle",
    "oracle_not_executed",
    "fake_assertion",
    "broad_exception_swallowing",
    "target_not_executed",
    "truncated_generation",
    "nondeterministic_failure",
)

SHAPE_DTYPE_PATTERNS = (
    re.compile(r"\bshape\b|size mismatch|sizes? of tensors? must match|size of tensor .* must match", re.I),
    re.compile(r"mat1 and mat2|dimension out of range|\bdimensional\b", re.I),
    re.compile(r"broadcast|invalid for input of size|expected input.*channel", re.I),
    re.compile(r"\bdtype\b|scalar type|type mismatch", re.I),
    re.compile(r"expected .*(?:shape|size|dim(?:ension)?|channel|dtype|scalar|tensor).* but got", re.I),
    re.compile(r"expected .*(?:shape|size|dim(?:ension)?|channel|dtype|scalar|tensor).*[,;:]\s*got", re.I),
    re.compile(r"expects? (?:a )?real input tensor.*but got", re.I),
    re.compile(r"not implemented for ['\"]?\w+", re.I),
)
UNDEFINED_NAME_PATTERN = re.compile(r"\bNameError:\s+name ['\"][^'\"]+['\"] is not defined", re.I)
ARGUMENT_SIGNATURE_PATTERNS = (
    re.compile(r"unexpected keyword argument|required positional argument", re.I),
    re.compile(r"missing \d+ required positional|got multiple values for argument", re.I),
    re.compile(r"invalid combination of arguments|takes .* but .* (?:was|were) given", re.I),
    re.compile(r"argument .+ must be .+[, ]not ", re.I),
    re.compile(r"expected .+ to be an instance .+[,;:]?\s*got", re.I),
)
INDEX_BOUNDS_PATTERN = re.compile(
    r"\bIndexError\b|index .+ out of (?:bounds?|range)|index out of .+ bound", re.I
)
ASSERTION_FAILURE_PATTERN = re.compile(r"\bAssertionError\b", re.I)
DIAGNOSTIC_LINE_PATTERN = re.compile(
    r"(?:^|\b)(?:AssertionError|IndexError|ImportError|ModuleNotFoundError|NameError|"
    r"NotImplementedError|RuntimeError|TypeError|ValueError|OSError|Exception)\b|"
    r"not implemented|not callable|out of (?:bounds?|range)",
    re.I,
)
DEPENDENCY_IMPORT_PATTERN = re.compile(r"\b(?:ModuleNotFoundError|ImportError):", re.I)
SETUP_ENVIRONMENT_PATTERNS = (
    re.compile(r"found no nvidia driver|cuda driver version is insufficient", re.I),
    re.compile(r"no cuda-capable device|cuda is not available|not compiled with cuda", re.I),
    re.compile(r"cannot open shared object file|undefined symbol", re.I),
)
RESOURCE_EXHAUSTION_PATTERN = re.compile(
    r"OutOfMemoryError|out of memory|CUDNN_STATUS_ALLOC_FAILED|cannot allocate memory", re.I
)
FOCAL_GROUP_CATEGORIES = (
    "syntax_error",
    "wrong_or_missing_target_api",
    "missing_import",
    "shape_or_dtype_error",
    "missing_oracle",
    "fake_assertion",
)
HARNESS_COMPARISON_CATEGORIES = (
    "syntax_error",
    "wrong_or_missing_target_api",
    "missing_oracle",
    "fake_assertion",
    "timeout",
)


def tri(value: Any) -> bool | None:
    """Convert only unambiguous evidence to a tri-state Boolean."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "yes", "pass", "passed", "1"}:
            return True
        if token in {"false", "no", "fail", "failed", "0"}:
            return False
        if token in {"", "none", "null", "unknown", "pending", "n/a"}:
            return None
    return None


def qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def iter_without_nested_definitions(nodes: Iterable[ast.AST]) -> Iterable[ast.AST]:
    """Walk executable module statements without entering function bodies."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def iter_statically_reachable(nodes: Iterable[ast.AST]) -> Iterable[ast.AST]:
    """Walk a scope while pruning branches proven dead by literal tests.

    Unknown conditions retain every branch because either may execute. This
    helper never evaluates names or calls and therefore cannot trigger model
    output or infer runtime state.
    """
    stack = list(reversed(list(nodes)))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            truth = static_boolean_value(node.test)
            children: list[ast.AST] = [node.test]
            if truth is True:
                children.extend(node.body)
            elif truth is False:
                children.extend(node.orelse)
            else:
                children.extend(node.body)
                children.extend(node.orelse)
            stack.extend(reversed(children))
            continue
        if isinstance(node, (ast.While, ast.IfExp)):
            test = node.test
            truth = static_boolean_value(test)
            if isinstance(node, ast.While):
                chosen = node.body if truth is not False else node.orelse
            elif truth is True:
                chosen = [node.body]
            elif truth is False:
                chosen = [node.orelse]
            else:
                chosen = [node.body, node.orelse]
            stack.extend(reversed([test, *chosen]))
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def import_aliases(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """Return simple import/assignment aliases and star-imported modules."""
    aliases: dict[str, str] = {}
    star_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                # `import torch.nn.functional` binds only `torch`; an explicit
                # `as F` binds the complete dotted module to F.
                aliases[bound] = alias.name if alias.asname else bound
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    star_modules.add(node.module)
                else:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    # Resolve direct callable aliases such as `op = torch.add`.  Iterate so
    # one alias may refer to another without attempting general data flow.
    for _ in range(3):
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            canonical = canonical_callable(value, aliases)
            if not canonical:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and aliases.get(target.id) != canonical:
                    aliases[target.id] = canonical
                    changed = True
        if not changed:
            break
    return aliases, star_modules


def canonical_callable(node: ast.AST, aliases: dict[str, str]) -> str | None:
    name = qualified_name(node)
    if name:
        head, *tail = name.split(".")
        if head in aliases:
            return ".".join([aliases[head], *tail])
        return name
    # Recognize direct dynamic lookup: getattr(torch, "add")(...).
    if isinstance(node, ast.Call) and qualified_name(node.func) == "getattr" and len(node.args) >= 2:
        base = canonical_callable(node.args[0], aliases)
        attr = node.args[1]
        if base and isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            return f"{base}.{attr.value}"
    return None


def target_call_matches(
    call: ast.Call, api: str, aliases: dict[str, str] | None = None, star_modules: set[str] | None = None
) -> bool:
    aliases = aliases or {}
    star_modules = star_modules or set()
    name = canonical_callable(call.func, aliases)
    if not name:
        return False
    if name == api:
        return True
    parent, _, tail = api.rpartition(".")
    if "." not in name and name == tail and parent in star_modules:
        return True
    # Tensor methods in the benchmark are normally invoked on an instance,
    # e.g. x.reshape(...) for torch.Tensor.reshape.
    if api.startswith("torch.Tensor."):
        return name.split(".")[-1] == api.rsplit(".", 1)[-1]
    return False


def target_match_descriptions(
    tree: ast.AST, api: str, aliases: dict[str, str], star_modules: set[str]
) -> list[str]:
    """Describe each AST target match using source spelling and canonical name."""
    descriptions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not target_call_matches(node, api, aliases, star_modules):
            continue
        source_name = qualified_name(node.func) or "<dynamic-call>"
        canonical = canonical_callable(node.func, aliases) or source_name
        detail = source_name if canonical == source_name else f"{source_name} -> {canonical}"
        if detail not in descriptions:
            descriptions.append(detail)
    return descriptions


def near_target_call_descriptions(
    tree: ast.AST, api: str, aliases: dict[str, str]
) -> list[str]:
    """Describe conservative API-variant near misses without changing labels."""
    target_tail = api.rsplit(".", 1)[-1]
    descriptions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        source_name = qualified_name(node.func) or ""
        canonical = canonical_callable(node.func, aliases) or source_name
        candidate_tail = canonical.rsplit(".", 1)[-1]
        reason: str | None = None
        if candidate_tail == target_tail and canonical != api:
            reason = "same terminal name on a different receiver"
        elif candidate_tail.rstrip("_") == target_tail.rstrip("_") and candidate_tail != target_tail:
            reason = "in-place/non-in-place name variant"
        elif target_tail.endswith("_tensor") and candidate_tail == target_tail.removesuffix("_tensor"):
            reason = "constructor name missing _tensor suffix"
        if reason:
            detail = f"{source_name or canonical} ({reason})"
            if detail not in descriptions:
                descriptions.append(detail)
    return descriptions


def is_oracle_node(node: ast.AST, aliases: dict[str, str] | None = None) -> bool:
    aliases = aliases or {}
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Raise) and node.exc is not None:
        raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        return canonical_callable(raised, aliases) in {"AssertionError", "builtins.AssertionError"}
    if not isinstance(node, ast.Call):
        return False
    name = canonical_callable(node.func, aliases) or ""
    return bool(
        name in {
            "torch._assert",
            "torch.testing.assert_close",
            "numpy.testing.assert_allclose",
            "numpy.testing.assert_array_equal",
            "numpy.testing.assert_equal",
            "unittest.TestCase.assertEqual",
            "unittest.TestCase.assertAlmostEqual",
            "unittest.TestCase.assertTrue",
            "unittest.TestCase.assertFalse",
        }
        or name.rsplit(".", 1)[-1] in {
            "assert_close", "assert_allclose", "assert_array_equal", "assert_equal",
            "assertEqual", "assertAlmostEqual", "assertTrue", "assertFalse",
        }
    )


def has_real_oracle(tree: ast.AST, aliases: dict[str, str] | None = None) -> bool:
    for node in ast.walk(tree):
        if is_oracle_node(node, aliases):
            return True
    return False


def reachable_top_level_functions(
    tree: ast.Module, aliases: dict[str, str]
) -> tuple[set[str], dict[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Conservatively resolve top-level helper calls, including direct aliases.

    This is deliberately not whole-program data-flow analysis.  It establishes
    only positive reachability from executable module statements through named
    top-level functions.  Dynamic dispatch and class methods remain unresolved.
    """
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def local_callee(node: ast.Call) -> str | None:
        name = canonical_callable(node.func, aliases)
        return name if name in functions else None

    call_graph: dict[str, set[str]] = {}
    for name, function in functions.items():
        call_graph[name] = {
            called for node in iter_statically_reachable(function.body)
            if isinstance(node, ast.Call)
            for called in [local_callee(node)]
            if called is not None
        }

    reachable = {
        called for node in iter_statically_reachable(tree.body)
        if isinstance(node, ast.Call)
        for called in [local_callee(node)]
        if called is not None
    }
    frontier = list(reachable)
    while frontier:
        caller = frontier.pop()
        for callee in call_graph.get(caller, set()):
            if callee not in reachable:
                reachable.add(callee)
                frontier.append(callee)
    return reachable, functions


def oracle_not_executed(
    tree: ast.Module, aliases: dict[str, str]
) -> tuple[bool | None, str]:
    """Check whether a syntactic oracle is reachable in standalone execution."""
    if not has_real_oracle(tree, aliases):
        return False, "no syntactic oracle to execute (reported separately)"

    module_nodes = list(iter_statically_reachable(tree.body))
    if any(is_oracle_node(node, aliases) for node in module_nodes):
        return False, "oracle occurs at module execution scope"

    reachable, functions = reachable_top_level_functions(tree, aliases)
    oracle_functions: set[str] = set()
    executable_oracle_functions: set[str] = set()
    for name, function in functions.items():
        if any(is_oracle_node(node, aliases) for node in iter_without_nested_definitions(function.body)):
            oracle_functions.add(name)
        if any(is_oracle_node(node, aliases) for node in iter_statically_reachable(function.body)):
            executable_oracle_functions.add(name)
    if executable_oracle_functions & reachable:
        return False, "oracle-containing function is reachable from module execution scope"
    if oracle_functions:
        return True, "oracle appears only on statically unreachable or uninvoked function path(s): " + ", ".join(sorted(oracle_functions))

    return None, "oracle exists but standalone reachability is unresolved"


def static_boolean_value(node: ast.AST) -> bool | None:
    """Evaluate only literal Boolean structure; never execute generated code."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = static_boolean_value(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
        left, right = node.left, node.comparators[0]
        if not isinstance(left, ast.Constant) or not isinstance(right, ast.Constant):
            return None
        a, b = left.value, right.value
        op = node.ops[0]
        try:
            if isinstance(op, (ast.Eq, ast.Is)):
                return a == b
            if isinstance(op, (ast.NotEq, ast.IsNot)):
                return a != b
            if isinstance(op, ast.Lt):
                return a < b
            if isinstance(op, ast.LtE):
                return a <= b
            if isinstance(op, ast.Gt):
                return a > b
            if isinstance(op, ast.GtE):
                return a >= b
        except TypeError:
            return None
    return None


def is_fake_assertion(tree: ast.AST, aliases: dict[str, str] | None = None) -> tuple[bool, str]:
    aliases = aliases or {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            test = node.test
            literal = static_boolean_value(test)
            if literal is not None:
                outcome = "passes" if literal else "fails"
                return True, f"literal-only assert always {outcome}"
            if isinstance(test, ast.Compare) and len(test.ops) == len(test.comparators) == 1:
                if isinstance(test.ops[0], (ast.Eq, ast.Is)):
                    if ast.dump(test.left) == ast.dump(test.comparators[0]):
                        return True, "self-comparison assert"
        if isinstance(node, ast.Call):
            name = canonical_callable(node.func, aliases) or ""
            terminal = name.rsplit(".", 1)[-1]
            if terminal in {
                "assert_close", "assert_allclose", "assert_array_equal", "assert_equal",
                "assertEqual", "assertAlmostEqual",
            } and len(node.args) >= 2:
                if ast.dump(node.args[0]) == ast.dump(node.args[1]):
                    return True, "oracle compares expression with itself"
            if name == "torch._assert" and node.args:
                literal = static_boolean_value(node.args[0])
                if literal is not None:
                    return True, f"literal-only torch._assert always {'passes' if literal else 'fails'}"
            if terminal in {"assertTrue", "assertFalse"} and node.args:
                literal = static_boolean_value(node.args[0])
                if literal is not None:
                    outcome = literal if terminal == "assertTrue" else not literal
                    return True, f"literal-only {terminal} always {'passes' if outcome else 'fails'}"
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Call):
            name = canonical_callable(node.test.func, aliases) or ""
            if (name.endswith("allclose") or name.endswith("equal")) and len(node.test.args) >= 2:
                if ast.dump(node.test.args[0]) == ast.dump(node.test.args[1]):
                    return True, "Boolean oracle compares expression with itself"
    return False, "no recognized fake assertion"


def broad_exception_swallowing(tree: ast.AST) -> tuple[bool, str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        names: set[str | None]
        if isinstance(node.type, ast.Tuple):
            names = {qualified_name(item) for item in node.type.elts}
        else:
            names = {qualified_name(node.type) if node.type else None}
        broad = bool(names & {None, "Exception", "BaseException"})
        handler_nodes = iter_without_nested_definitions(node.body)
        if broad and not any(isinstance(child, ast.Raise) for child in handler_nodes):
            name = ",".join("bare except" if n is None else n for n in sorted(names, key=str))
            return True, f"broad handler {name or 'bare except'} has no re-raise"
    return False, "no swallowing broad handler"


def missing_import(tree: ast.AST, stderr: str) -> tuple[bool, str]:
    match = re.search(r"NameError:\s+name ['\"]([^'\"]+)['\"] is not defined", stderr)
    known_module_aliases = {
        "torch", "np", "numpy", "F", "nn", "math", "random", "os", "sys", "time",
        "functools", "itertools", "operator", "pytest",
    }
    if match and match.group(1) in known_module_aliases:
        return True, f"runtime NameError for {match.group(1)}"

    def names_in_scope(nodes: Iterable[ast.AST], parameters: Iterable[str] = ()) -> tuple[set[str], set[str]]:
        bound = set(parameters)
        loaded: set[str] = set()
        for node in iter_statically_reachable(nodes):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        bound.add(alias.asname or alias.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    loaded.add(node.id)
                elif isinstance(node.ctx, (ast.Store, ast.Param)):
                    bound.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
        return bound, loaded

    if not isinstance(tree, ast.Module):
        return False, "all referenced known module aliases are bound"
    module_bound, module_loaded = names_in_scope(tree.body)
    missing_by_scope: list[str] = []
    missing_module = sorted((module_loaded & known_module_aliases) - module_bound)
    if missing_module:
        missing_by_scope.append("module:" + ",".join(missing_module))
    for function in (
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        parameters = [arg.arg for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)]
        if function.args.vararg:
            parameters.append(function.args.vararg.arg)
        if function.args.kwarg:
            parameters.append(function.args.kwarg.arg)
        local_bound, local_loaded = names_in_scope(function.body, parameters)
        missing_local = sorted(
            (local_loaded & known_module_aliases) - local_bound - module_bound
        )
        if missing_local:
            missing_by_scope.append(f"{function.name}:" + ",".join(missing_local))
    if missing_by_scope:
        return True, "unbound module alias(es) by scope: " + "; ".join(missing_by_scope)
    return False, "all referenced known module aliases are bound"


def target_not_executed(
    tree: ast.Module, api: str, target_present: bool, aliases: dict[str, str], star_modules: set[str]
) -> tuple[bool, str]:
    if not target_present:
        return False, "no target call to execute (reported separately)"

    reachable, functions = reachable_top_level_functions(tree, aliases)
    functions_with_target: set[str] = set()
    executable_target_functions: set[str] = set()
    for name, function in functions.items():
        if any(
            isinstance(node, ast.Call) and target_call_matches(node, api, aliases, star_modules)
            for node in iter_without_nested_definitions(function.body)
        ):
            functions_with_target.add(name)
        if any(
            isinstance(node, ast.Call) and target_call_matches(node, api, aliases, star_modules)
            for node in iter_statically_reachable(function.body)
        ):
            executable_target_functions.add(name)

    module_nodes = list(iter_statically_reachable(tree.body))
    if any(
        isinstance(n, ast.Call) and target_call_matches(n, api, aliases, star_modules) for n in module_nodes
    ):
        return False, "target API is invoked at module execution scope"

    if executable_target_functions & reachable:
        return False, "target-containing function is reachable from module execution scope"
    if functions_with_target:
        return True, "target appears only on statically unreachable or uninvoked function path(s): " + ", ".join(sorted(functions_with_target))
    module_target_any = any(
        isinstance(node, ast.Call) and target_call_matches(node, api, aliases, star_modules)
        for node in iter_without_nested_definitions(tree.body)
    )
    if module_target_any:
        return True, "target appears only on a statically unreachable module path"
    # A target call can be inside a class/method.  Conservatively mark unknown
    # rather than claiming that it did not run.
    return False, "target execution is not disproven"


def classify_record(record: dict[str, Any]) -> tuple[dict[str, bool | None], dict[str, str]]:
    code_value = record.get("extracted_code")
    code = code_value if isinstance(code_value, str) else record.get("raw_output")
    api = str(record.get("api") or "")
    status: dict[str, bool | None] = {name: None for name in CATEGORIES}
    evidence: dict[str, str] = {name: "insufficient evidence" for name in CATEGORIES}

    tree: ast.Module | None = None
    if not isinstance(code, str) or not code.strip():
        evidence["syntax_error"] = "no extracted code"
    else:
        try:
            tree = ast.parse(code)
            status["syntax_error"] = False
            evidence["syntax_error"] = "ast.parse succeeded"
        except SyntaxError as exc:
            status["syntax_error"] = True
            evidence["syntax_error"] = f"{exc.msg} (line {exc.lineno})"

    timeout_value = tri(record.get("timeout")) if "timeout" in record else None
    status["timeout"] = timeout_value
    evidence["timeout"] = "recorded timeout flag" if timeout_value is not None else "timeout flag absent"

    finish_reason = record.get("finish_reason")
    if isinstance(finish_reason, str):
        status["truncated_generation"] = finish_reason.lower() == "length"
        evidence["truncated_generation"] = f"finish_reason={finish_reason}"

    reproducible = tri(record.get("reproducible")) if "reproducible" in record else None
    if reproducible is not None:
        status["nondeterministic_failure"] = not reproducible
        evidence["nondeterministic_failure"] = f"recorded reproducible={str(reproducible).lower()}"
    else:
        replay_outcomes = record.get("replay_outcomes")
        if isinstance(replay_outcomes, list) and len(replay_outcomes) >= 2:
            canonical = {json.dumps(value, sort_keys=True, default=str) for value in replay_outcomes}
            status["nondeterministic_failure"] = len(canonical) > 1
            evidence["nondeterministic_failure"] = f"{len(canonical)} distinct outcomes across {len(replay_outcomes)} replays"

    stderr = str(record.get("stderr") or "")
    exit_code = record.get("exit_code")
    execution_known = isinstance(exit_code, int)
    if execution_known:
        runtime_failed = exit_code != 0
        matched = next((p.pattern for p in SHAPE_DTYPE_PATTERNS if p.search(stderr)), None)
        status["shape_or_dtype_error"] = bool(runtime_failed and matched)
        evidence["shape_or_dtype_error"] = (
            f"matched runtime diagnostic /{matched}/" if runtime_failed and matched
            else f"exit_code={exit_code}; no matching shape/dtype diagnostic"
        )
        index_error = bool(runtime_failed and INDEX_BOUNDS_PATTERN.search(stderr))
        status["index_or_bounds_error"] = index_error
        evidence["index_or_bounds_error"] = (
            "runtime index/bounds diagnostic"
            if index_error else f"exit_code={exit_code}; no index/bounds diagnostic"
        )
        undefined_name = bool(runtime_failed and UNDEFINED_NAME_PATTERN.search(stderr))
        status["undefined_name_error"] = undefined_name
        evidence["undefined_name_error"] = (
            "runtime NameError diagnostic" if undefined_name else f"exit_code={exit_code}; no NameError diagnostic"
        )
        argument_pattern = next((p.pattern for p in ARGUMENT_SIGNATURE_PATTERNS if p.search(stderr)), None)
        status["argument_signature_error"] = bool(runtime_failed and argument_pattern)
        evidence["argument_signature_error"] = (
            f"matched runtime diagnostic /{argument_pattern}/"
            if runtime_failed and argument_pattern else f"exit_code={exit_code}; no argument/signature diagnostic"
        )
        dependency_error = bool(runtime_failed and DEPENDENCY_IMPORT_PATTERN.search(stderr))
        status["dependency_import_error"] = dependency_error
        evidence["dependency_import_error"] = (
            "runtime dependency import diagnostic"
            if dependency_error else f"exit_code={exit_code}; no dependency import diagnostic"
        )
        setup_pattern = next((p.pattern for p in SETUP_ENVIRONMENT_PATTERNS if p.search(stderr)), None)
        status["setup_or_environment_error"] = bool(runtime_failed and setup_pattern)
        evidence["setup_or_environment_error"] = (
            f"matched runtime diagnostic /{setup_pattern}/"
            if runtime_failed and setup_pattern else f"exit_code={exit_code}; no setup/environment diagnostic"
        )
        resource_error = bool(runtime_failed and RESOURCE_EXHAUSTION_PATTERN.search(stderr))
        status["resource_exhaustion"] = resource_error
        evidence["resource_exhaustion"] = (
            "runtime resource-exhaustion diagnostic"
            if resource_error else f"exit_code={exit_code}; no resource-exhaustion diagnostic"
        )
        assertion_failure = bool(runtime_failed and ASSERTION_FAILURE_PATTERN.search(stderr))
        status["assertion_failure"] = assertion_failure
        evidence["assertion_failure"] = (
            "subprocess terminated with AssertionError"
            if assertion_failure else f"exit_code={exit_code}; no AssertionError diagnostic"
        )
        classified_runtime = bool(
            matched or index_error or undefined_name or argument_pattern or dependency_error
            or setup_pattern or resource_error or assertion_failure
        )
        status["runtime_error_other"] = bool(
            runtime_failed and not classified_runtime and timeout_value is not True
        )
        evidence["runtime_error_other"] = (
            "nonzero exit without a recognized specific diagnostic or timeout"
            if status["runtime_error_other"] else f"exit_code={exit_code}"
        )
    else:
        evidence["shape_or_dtype_error"] = "subprocess did not produce an exit code"
        evidence["index_or_bounds_error"] = "subprocess did not produce an exit code"
        evidence["undefined_name_error"] = "subprocess did not produce an exit code"
        evidence["argument_signature_error"] = "subprocess did not produce an exit code"
        evidence["dependency_import_error"] = "subprocess did not produce an exit code"
        evidence["setup_or_environment_error"] = "subprocess did not produce an exit code"
        evidence["resource_exhaustion"] = "subprocess did not produce an exit code"
        evidence["runtime_error_other"] = "subprocess did not produce an exit code"
        evidence["assertion_failure"] = "subprocess did not produce an exit code"

    if tree is None:
        # Fields emitted after a failed AST parse are often default False, not
        # negative observations.  They intentionally remain unknown here.
        return status, evidence

    aliases, star_modules = import_aliases(tree)
    if not api:
        evidence["wrong_or_missing_target_api"] = "target API name absent"
        evidence["target_not_executed"] = "target API name absent"
        target_present = False
    else:
        target_field = tri(record.get("target_call_present")) if "target_call_present" in record else None
        target_matches = target_match_descriptions(tree, api, aliases, star_modules)
        target_ast = bool(target_matches)
        target_present = target_field is True or target_ast
        status["wrong_or_missing_target_api"] = not target_present
        if target_ast:
            evidence["wrong_or_missing_target_api"] = (
                f"harness target_call_present={str(target_field).lower()}; "
                f"AST matched {target_matches[0]} to {api}"
            )
        elif target_field is True:
            evidence["wrong_or_missing_target_api"] = (
                "harness target_call_present=true; analyzer found no independent AST match"
            )
        else:
            near_matches = near_target_call_descriptions(tree, api, aliases)
            suffix = f"; near call {near_matches[0]}" if near_matches else ""
            evidence["wrong_or_missing_target_api"] = f"no exact AST call matching {api}{suffix}"

    missing, why = missing_import(tree, stderr)
    status["missing_import"], evidence["missing_import"] = missing, why

    oracle_field = tri(record.get("oracle_present")) if "oracle_present" in record else None
    oracle_ast = has_real_oracle(tree, aliases)
    oracle_present = oracle_field is True or oracle_ast
    status["missing_oracle"] = not oracle_present
    evidence["missing_oracle"] = "recognized syntactic oracle" if oracle_present else "no recognized syntactic oracle"

    not_executed, why = oracle_not_executed(tree, aliases)
    status["oracle_not_executed"], evidence["oracle_not_executed"] = not_executed, why

    fake, why = is_fake_assertion(tree, aliases)
    recorded_fake = tri(record.get("fake_assertion")) if "fake_assertion" in record else None
    status["fake_assertion"] = bool(fake or recorded_fake is True)
    evidence["fake_assertion"] = why if fake else (
        "benchmark recorded fake_assertion=true" if recorded_fake is True else why
    )

    broad, why = broad_exception_swallowing(tree)
    status["broad_exception_swallowing"], evidence["broad_exception_swallowing"] = broad, why

    if api:
        not_run, why = target_not_executed(tree, api, target_present, aliases, star_modules)
        status["target_not_executed"], evidence["target_not_executed"] = not_run, why
    return status, evidence


def harness_expected_labels(record: dict[str, Any]) -> dict[str, bool | None]:
    """Translate only semantically valid harness fields to failure labels.

    Several runner fields default to false after parsing fails. Those defaults
    are not negative observations, so target/oracle/fake-assertion comparisons
    are eligible only when the harness positively records parseability.
    """
    labels: dict[str, bool | None] = {name: None for name in HARNESS_COMPARISON_CATEGORIES}
    parseable = tri(record.get("parseable")) if "parseable" in record else None
    if parseable is not None:
        labels["syntax_error"] = not parseable
    if parseable is True:
        target = tri(record.get("target_call_present")) if "target_call_present" in record else None
        oracle = tri(record.get("oracle_present")) if "oracle_present" in record else None
        fake = tri(record.get("fake_assertion")) if "fake_assertion" in record else None
        labels["wrong_or_missing_target_api"] = None if target is None else not target
        labels["missing_oracle"] = None if oracle is None else not oracle
        labels["fake_assertion"] = fake
    labels["timeout"] = tri(record.get("timeout")) if "timeout" in record else None
    return labels


def source_role(path: Path) -> str:
    return "smoke_validation" if "smoke" in str(path).lower() else "campaign_checkpoint"


def load_source(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    # Read one immutable byte snapshot.  A Colab checkpoint may be appended
    # while this analysis is running; parsing and hashing different states
    # would make the manifest unverifiable.
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: input is not UTF-8: {exc}") from exc
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        value = dict(value)
        value["_source_record_index"] = line_number
        records.append(value)
    metadata = {
        "path": str(path.resolve()),
        "label": f"{path.parent.name}_{path.stem}" if source_role(path) == "smoke_validation" else path.stem,
        "role": source_role(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "records": len(records),
    }
    return records, metadata


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """Two-sided Wilson score interval; undefined when no denominator exists."""
    if total <= 0:
        return None, None
    proportion = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = z * math.sqrt((proportion * (1.0 - proportion) + z2 / (4.0 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def summarize(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_keys: list[tuple[str, tuple[str, ...]]] = [
        ("source", ("source", "source_role")),
        ("baseline", ("source", "source_role", "baseline")),
        ("baseline_group", ("source", "source_role", "baseline", "api_group")),
        ("seed", ("source", "source_role", "generation_seed")),
        ("seed_baseline", ("source", "source_role", "generation_seed", "baseline")),
        (
            "seed_baseline_group",
            ("source", "source_role", "generation_seed", "baseline", "api_group"),
        ),
    ]
    for level, keys in group_keys:
        buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for item in classified:
            key = tuple(item.get(k) for k in keys)
            buckets.setdefault(key, []).append(item)
        for key, items in sorted(buckets.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
            dimensions = dict(zip(keys, key))
            for category in CATEGORIES:
                counts = Counter("unknown" if i[category] is None else str(i[category]).lower() for i in items)
                n_true, n_false, n_unknown = counts["true"], counts["false"], counts["unknown"]
                n_known = n_true + n_false
                rows.append({
                    "aggregation": level,
                    **dimensions,
                    "baseline": dimensions.get("baseline", "__ALL__"),
                    "api_group": dimensions.get("api_group", "__ALL__"),
                    "generation_seed": dimensions.get("generation_seed", "__ALL__"),
                    "category": category,
                    "n_total": len(items),
                    "n_known": n_known,
                    "n_true": n_true,
                    "n_false": n_false,
                    "n_unknown": n_unknown,
                    "failure_rate_known": rate(n_true, n_known),
                    "failure_rate_total_lower_bound": rate(n_true, len(items)),
                })
    return rows


def coverage_rows(
    classified: list[dict[str, Any]], sources: list[dict[str, Any]], expected_per_baseline: int,
    expected_per_group: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_source = {s["label"]: s for s in sources}
    for source, meta in sorted(by_source.items()):
        records = [r for r in classified if r["source"] == source]
        groups = sorted({str(r["api_group"]) for r in records})
        for baseline in EXPECTED_BASELINES:
            baseline_records = [r for r in records if r["baseline"] == baseline]
            baseline_ids = {
                str(r["task_id"]) for r in baseline_records if r.get("task_id") not in (None, "")
            }
            observed = len(baseline_ids)
            expected = expected_per_baseline if meta["role"] == "campaign_checkpoint" else None
            rows.append({
                "source": source,
                "source_role": meta["role"],
                "baseline": baseline,
                "api_group": "__ALL__",
                # Coverage is based on unique, auditable task identities.  Raw
                # rows are retained separately so duplicate appends cannot
                # make an incomplete campaign look complete.
                "raw_records": len(baseline_records),
                "observed_records": observed,
                "duplicate_records": max(len(baseline_records) - observed - sum(
                    r.get("task_id") in (None, "") for r in baseline_records
                ), 0),
                "unidentified_records": sum(
                    r.get("task_id") in (None, "") for r in baseline_records
                ),
                "expected_records": expected,
                "missing_records": max(expected - observed, 0) if expected is not None else None,
                "coverage_rate": rate(observed, expected) if expected else None,
            })
            for group in groups:
                group_records = [r for r in baseline_records if r["api_group"] == group]
                group_ids = {
                    str(r["task_id"]) for r in group_records if r.get("task_id") not in (None, "")
                }
                count = len(group_ids)
                unidentified = sum(r.get("task_id") in (None, "") for r in group_records)
                group_expected = expected_per_group if meta["role"] == "campaign_checkpoint" else None
                rows.append({
                    "source": source,
                    "source_role": meta["role"],
                    "baseline": baseline,
                    "api_group": group,
                    "raw_records": len(group_records),
                    "observed_records": count,
                    "duplicate_records": max(len(group_records) - count - unidentified, 0),
                    "unidentified_records": unidentified,
                    "expected_records": group_expected,
                    "missing_records": max(group_expected - count, 0) if group_expected is not None else None,
                    "coverage_rate": rate(count, group_expected) if group_expected else None,
                })
    return rows


def combined_campaign_view(
    classified: list[dict[str, Any]], expected_per_baseline: int, expected_per_group: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Aggregate campaign shards while scaling expectations by distinct seeds."""
    campaign = [item for item in classified if item["source_role"] == "campaign_checkpoint"]
    source_labels = sorted({str(item["source"]) for item in campaign})
    seeds = sorted(
        {str(item["generation_seed"]) for item in campaign if item.get("generation_seed") not in (None, "")}
    )
    unknown_seed_sources = sorted({
        str(item["source"]) for item in campaign if item.get("generation_seed") in (None, "")
    })
    # Known seeds identify shards across files. Each source containing
    # seed-less campaign records remains a separate conservative shard rather
    # than disappearing merely because another source has a known seed.
    shard_count = len(seeds) + len(unknown_seed_sources)
    if not campaign:
        return [], [], [], {
            "source_labels": [], "generation_seeds": [], "unknown_seed_sources": [], "shard_count": 0,
            "expected_per_baseline": 0, "expected_per_api_group": 0,
        }

    combined = campaign_combined_records(classified)
    summary = summarize(combined)
    # coverage_rows assigns expectations only to campaign_checkpoint metadata;
    # rewrite the role after computation so this synthetic view cannot be
    # mistaken for an independently observed shard.
    synthetic_source = [{"label": "campaign_combined", "role": "campaign_checkpoint"}]
    coverage = coverage_rows(
        combined,
        synthetic_source,
        expected_per_baseline * shard_count,
        expected_per_group * shard_count,
    )
    for row in coverage:
        row["source_role"] = "campaign_combined"
    group_rates = group_error_rate_rows(summary, coverage)
    metadata = {
        "source_labels": source_labels,
        "generation_seeds": seeds,
        "unknown_seed_sources": unknown_seed_sources,
        "shard_count": shard_count,
        "expected_per_baseline": expected_per_baseline * shard_count,
        "expected_per_api_group": expected_per_group * shard_count,
    }
    return summary, coverage, group_rates, metadata


def campaign_combined_records(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project all campaign shards into one explicitly synthetic analysis source."""
    return [
        {**item, "source": "campaign_combined", "source_role": "campaign_combined"}
        for item in classified
        if item["source_role"] == "campaign_checkpoint"
    ]


def group_error_rate_rows(
    summary: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join baseline-by-group tri-state rates to explicit completeness evidence."""
    indexed = {
        (row["source"], row["baseline"], row["api_group"], row["category"]): row
        for row in summary
        if row["aggregation"] == "baseline_group"
    }
    rows: list[dict[str, Any]] = []
    for cov in coverage:
        if cov["api_group"] == "__ALL__":
            continue
        for category in CATEGORIES:
            item = indexed.get((cov["source"], cov["baseline"], cov["api_group"], category), {})
            n_total = int(item.get("n_total", 0))
            n_known = int(item.get("n_known", 0))
            n_true = int(item.get("n_true", 0))
            n_false = int(item.get("n_false", 0))
            n_unknown = int(item.get("n_unknown", 0))
            low, high = wilson_interval(n_true, n_known)
            rows.append({
                "source": cov["source"],
                "source_role": cov["source_role"],
                "baseline": cov["baseline"],
                "api_group": cov["api_group"],
                "category": category,
                "n_total": n_total,
                "n_known": n_known,
                "n_true": n_true,
                "n_false": n_false,
                "n_unknown": n_unknown,
                "failure_rate_known": rate(n_true, n_known),
                "wilson_95_low": low,
                "wilson_95_high": high,
                "observed_records": cov["observed_records"],
                "raw_records": cov.get("raw_records", cov["observed_records"]),
                "duplicate_records": cov.get("duplicate_records", 0),
                "unidentified_records": cov.get("unidentified_records", 0),
                "expected_records": cov["expected_records"],
                "missing_records": cov["missing_records"],
                "coverage_rate": cov["coverage_rate"],
            })
    return rows


def truncation_association_rows(
    classified: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Describe within-baseline truncation associations without causal interpretation."""
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in classified:
        key = (item["source"], item["source_role"], item["baseline"])
        buckets.setdefault(key, []).append(item)

    rows: list[dict[str, Any]] = []
    outcome_names = ("parseable", "oracle_bearing", "standalone_oracle_reachable")

    def outcome_value(item: dict[str, Any], outcome: str) -> bool | None:
        if outcome == "parseable":
            failure = item.get("syntax_error")
            return None if failure is None else failure is False
        if outcome == "oracle_bearing":
            failure = item.get("missing_oracle")
            return None if failure is None else failure is False
        missing = item.get("missing_oracle")
        unreachable = item.get("oracle_not_executed")
        if missing is None:
            return None
        if missing is True:
            return False
        if unreachable is None:
            return None
        return unreachable is False
    overall_coverage = sorted(
        (row for row in coverage if row["api_group"] == "__ALL__"),
        key=lambda row: (row["source"], row["baseline"]),
    )
    for cov in overall_coverage:
        source, role, baseline = cov["source"], cov["source_role"], cov["baseline"]
        items = buckets.get((source, role, baseline), [])
        for outcome in outcome_names:
            counts = {True: [0, 0], False: [0, 0]}  # truncation -> [eligible, outcome-positive]
            unknown_truncation = 0
            unknown_outcome = 0
            for item in items:
                truncated = item["truncated_generation"]
                positive = outcome_value(item, outcome)
                if truncated is None:
                    unknown_truncation += 1
                    continue
                if positive is None:
                    unknown_outcome += 1
                    continue
                counts[bool(truncated)][0] += 1
                counts[bool(truncated)][1] += int(positive)
            truncated_n, truncated_positive = counts[True]
            nontruncated_n, nontruncated_positive = counts[False]
            truncated_rate = rate(truncated_positive, truncated_n)
            nontruncated_rate = rate(nontruncated_positive, nontruncated_n)
            truncated_low, truncated_high = wilson_interval(truncated_positive, truncated_n)
            nontruncated_low, nontruncated_high = wilson_interval(nontruncated_positive, nontruncated_n)
            rows.append({
                "source": source,
                "source_role": role,
                "baseline": baseline,
                "outcome": outcome,
                "n_total": len(items),
                "n_eligible": truncated_n + nontruncated_n,
                "unknown_truncation": unknown_truncation,
                "unknown_outcome": unknown_outcome,
                "truncated_n": truncated_n,
                "truncated_outcome_positive": truncated_positive,
                "truncated_rate": truncated_rate,
                "truncated_wilson_95_low": truncated_low,
                "truncated_wilson_95_high": truncated_high,
                "nontruncated_n": nontruncated_n,
                "nontruncated_outcome_positive": nontruncated_positive,
                "nontruncated_rate": nontruncated_rate,
                "nontruncated_wilson_95_low": nontruncated_low,
                "nontruncated_wilson_95_high": nontruncated_high,
                "risk_difference_truncated_minus_nontruncated": (
                    truncated_rate - nontruncated_rate
                    if truncated_rate is not None and nontruncated_rate is not None else None
                ),
                "observed_records": cov["observed_records"],
                "raw_records": cov.get("raw_records", cov["observed_records"]),
                "duplicate_records": cov.get("duplicate_records", 0),
                "unidentified_records": cov.get("unidentified_records", 0),
                "expected_records": cov["expected_records"],
                "missing_records": cov["missing_records"],
                "coverage_rate": cov["coverage_rate"],
            })
    return rows


def empirical_quantile(values: list[float], probability: float) -> float | None:
    """Return a deterministic nearest-rank empirical quantile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def length_diagnostic_rows(
    classified: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Summarize finish reasons, token counts, and generation time per baseline."""
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in classified:
        key = (item["source"], item["source_role"], item["baseline"])
        buckets.setdefault(key, []).append(item)

    rows: list[dict[str, Any]] = []
    overall_coverage = sorted(
        (row for row in coverage if row["api_group"] == "__ALL__"),
        key=lambda row: (row["source"], row["baseline"]),
    )
    for cov in overall_coverage:
        key = (cov["source"], cov["source_role"], cov["baseline"])
        items = buckets.get(key, [])
        reasons = sorted({str(item.get("finish_reason") or "__UNKNOWN__") for item in items})
        for finish_reason in ["__ALL__", *reasons]:
            selected = items if finish_reason == "__ALL__" else [
                item for item in items
                if str(item.get("finish_reason") or "__UNKNOWN__") == finish_reason
            ]
            tokens = [
                float(item["raw_token_count"]) for item in selected
                if isinstance(item.get("raw_token_count"), (int, float))
            ]
            seconds = [
                float(item["generation_seconds"]) for item in selected
                if isinstance(item.get("generation_seconds"), (int, float))
            ]
            subprocess_seconds = [
                float(item["subprocess_seconds"]) for item in selected
                if isinstance(item.get("subprocess_seconds"), (int, float))
            ]
            paired = [
                (float(item["raw_token_count"]), float(item["generation_seconds"]))
                for item in selected
                if isinstance(item.get("raw_token_count"), (int, float))
                and isinstance(item.get("generation_seconds"), (int, float))
                and float(item["generation_seconds"]) > 0
            ]
            per_record_throughput = [token_count / duration for token_count, duration in paired]
            rows.append({
                "source": cov["source"],
                "source_role": cov["source_role"],
                "baseline": cov["baseline"],
                "finish_reason": finish_reason,
                "n_records": len(selected),
                "observed_records": cov["observed_records"],
                "expected_records": cov["expected_records"],
                "missing_records": cov["missing_records"],
                "n_token_count_known": len(tokens),
                "tokens_min": min(tokens) if tokens else None,
                "tokens_median": empirical_quantile(tokens, 0.5),
                "tokens_p95": empirical_quantile(tokens, 0.95),
                "tokens_max": max(tokens) if tokens else None,
                "n_generation_seconds_known": len(seconds),
                "generation_seconds_total": sum(seconds) if seconds else None,
                "generation_seconds_mean": sum(seconds) / len(seconds) if seconds else None,
                "generation_seconds_p95": empirical_quantile(seconds, 0.95),
                "n_subprocess_seconds_known": len(subprocess_seconds),
                "subprocess_seconds_total": sum(subprocess_seconds) if subprocess_seconds else None,
                "subprocess_seconds_mean": (
                    sum(subprocess_seconds) / len(subprocess_seconds) if subprocess_seconds else None
                ),
                "n_token_generation_pairs": len(paired),
                "aggregate_tokens_per_generation_second": (
                    sum(token_count for token_count, _ in paired) / sum(duration for _, duration in paired)
                    if paired else None
                ),
                "per_record_tokens_per_second_median": empirical_quantile(per_record_throughput, 0.5),
                "per_record_tokens_per_second_p95": empirical_quantile(per_record_throughput, 0.95),
            })
    return rows


def seed_telemetry_rows(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate runtime telemetry by generation seed and baseline.

    Coverage is identity-based. Throughput uses only records with both a token
    count and a positive generation duration; missing telemetry is not imputed.
    """
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in classified:
        seed = "__UNKNOWN__" if item.get("generation_seed") in (None, "") else str(item["generation_seed"])
        key = (item["source"], item["source_role"], seed, item["baseline"])
        buckets.setdefault(key, []).append(item)

    rows: list[dict[str, Any]] = []
    for (source, role, seed, baseline), items in sorted(buckets.items()):
        identities = {
            str(item["task_id"]) for item in items if item.get("task_id") not in (None, "")
        }
        tokens = [
            float(item["raw_token_count"]) for item in items
            if isinstance(item.get("raw_token_count"), (int, float))
        ]
        generation = [
            float(item["generation_seconds"]) for item in items
            if isinstance(item.get("generation_seconds"), (int, float))
        ]
        subprocess = [
            float(item["subprocess_seconds"]) for item in items
            if isinstance(item.get("subprocess_seconds"), (int, float))
        ]
        paired = [
            (float(item["raw_token_count"]), float(item["generation_seconds"]))
            for item in items
            if isinstance(item.get("raw_token_count"), (int, float))
            and isinstance(item.get("generation_seconds"), (int, float))
            and float(item["generation_seconds"]) > 0
        ]
        throughput = [token_count / duration for token_count, duration in paired]
        rows.append({
            "source": source,
            "source_role": role,
            "generation_seed": seed,
            "baseline": baseline,
            "raw_records": len(items),
            "unique_tasks": len(identities),
            "unidentified_records": sum(item.get("task_id") in (None, "") for item in items),
            "n_token_count_known": len(tokens),
            "tokens_total": sum(tokens) if tokens else None,
            "tokens_median": empirical_quantile(tokens, 0.5),
            "n_generation_seconds_known": len(generation),
            "generation_seconds_total": sum(generation) if generation else None,
            "generation_seconds_mean": sum(generation) / len(generation) if generation else None,
            "n_subprocess_seconds_known": len(subprocess),
            "subprocess_seconds_total": sum(subprocess) if subprocess else None,
            "subprocess_seconds_mean": sum(subprocess) / len(subprocess) if subprocess else None,
            "n_token_generation_pairs": len(paired),
            "aggregate_tokens_per_generation_second": (
                sum(token_count for token_count, _ in paired) / sum(duration for _, duration in paired)
                if paired else None
            ),
            "per_record_tokens_per_second_median": empirical_quantile(throughput, 0.5),
            "per_record_tokens_per_second_p95": empirical_quantile(throughput, 0.95),
        })
    return rows


def integrity_rows(classified: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Audit ledger identity fields without altering or deduplicating evidence."""
    rows: list[dict[str, Any]] = []
    for meta in sources:
        records = [item for item in classified if item["source"] == meta["label"]]
        identities = Counter(
            (item["baseline"], item["task_id"])
            for item in records
            if item.get("task_id") not in (None, "")
        )
        rows.append({
            "source": meta["label"],
            "source_role": meta["role"],
            "records": len(records),
            "missing_task_id_records": sum(item.get("task_id") in (None, "") for item in records),
            "duplicate_task_baseline_records": sum(count - 1 for count in identities.values() if count > 1),
            "unexpected_baseline_records": sum(
                item["baseline"] not in EXPECTED_BASELINES for item in records
            ),
            "run_signatures": sorted({str(item["run_signature"]) for item in records if item.get("run_signature")}),
            "generation_seeds": sorted(
                {str(item["generation_seed"]) for item in records if item.get("generation_seed") is not None}
            ),
        })
    return rows


def harness_comparison_rows(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Audit analyzer/harness agreement without treating either as ground truth."""
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in classified:
        key = (item["source"], item["source_role"], item["baseline"])
        buckets.setdefault(key, []).append(item)
    rows: list[dict[str, Any]] = []
    for (source, role, baseline), items in sorted(buckets.items()):
        for category in HARNESS_COMPARISON_CATEGORIES:
            harness_unknown = analyzer_unknown = comparable = agree = 0
            harness_true_analyzer_false = harness_false_analyzer_true = 0
            for item in items:
                expected = item["harness_expected"].get(category)
                observed = item.get(category)
                if expected is None:
                    harness_unknown += 1
                    continue
                if observed is None:
                    analyzer_unknown += 1
                    continue
                comparable += 1
                agree += int(expected is observed)
                harness_true_analyzer_false += int(expected is True and observed is False)
                harness_false_analyzer_true += int(expected is False and observed is True)
            rows.append({
                "source": source,
                "source_role": role,
                "baseline": baseline,
                "category": category,
                "n_total": len(items),
                "n_comparable": comparable,
                "n_agree": agree,
                "n_disagree": comparable - agree,
                "n_harness_true_analyzer_false": harness_true_analyzer_false,
                "n_harness_false_analyzer_true": harness_false_analyzer_true,
                "n_harness_unknown": harness_unknown,
                "n_analyzer_unknown_given_harness_known": analyzer_unknown,
                "agreement_rate": rate(agree, comparable),
            })
    return rows


def harness_disagreement_rows(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize row-level analyzer/harness disagreements for manual audit."""
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        classified,
        key=lambda item: (str(item["source"]), str(item["baseline"]), int(item["source_record_index"])),
    )
    for item in ordered:
        for category in HARNESS_COMPARISON_CATEGORIES:
            harness = item["harness_expected"].get(category)
            analyzer = item.get(category)
            if harness is None or analyzer is None or harness is analyzer:
                continue
            rows.append({
                "source": item["source"],
                "source_role": item["source_role"],
                "source_sha256": item["source_sha256"],
                "source_record_index": item["source_record_index"],
                "baseline": item["baseline"],
                "category": category,
                "harness_label": harness,
                "analyzer_label": analyzer,
                "task_id": item["task_id"],
                "api_group": item["api_group"],
                "api": item["api"],
                "generation_seed": item["generation_seed"],
                "raw_output_sha256": item["raw_output_sha256"],
                "analyzer_evidence": item["evidence"].get(category, ""),
            })
    return rows


def case_catalog_rows(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose the first auditable positive example per source/baseline/category."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    ordered = sorted(
        classified,
        key=lambda item: (str(item["source"]), str(item["baseline"]), int(item["source_record_index"])),
    )
    for item in ordered:
        for category in CATEGORIES:
            key = (str(item["source"]), str(item["baseline"]), category)
            if item[category] is not True or key in seen:
                continue
            seen.add(key)
            rows.append({
                "source": item["source"],
                "source_role": item["source_role"],
                "source_sha256": item["source_sha256"],
                "source_record_index": item["source_record_index"],
                "baseline": item["baseline"],
                "category": category,
                "task_id": item["task_id"],
                "api_group": item["api_group"],
                "api": item["api"],
                "generation_seed": item["generation_seed"],
                "exit_code": item.get("exit_code"),
                "stderr_excerpt": item.get("stderr_excerpt", ""),
                "raw_output_sha256": item["raw_output_sha256"],
                "evidence": item["evidence"][category],
            })
    return rows


def diagnostic_excerpt(stderr: Any, limit: int = 240) -> str:
    """Return a bounded, single-line runtime diagnostic for audit tables.

    PyTorch may emit thousands of backend-registration lines around the useful
    exception. Prefer the last explicit exception/diagnostic line; if the
    harness retained no such line, preserve a bounded start/end marker rather
    than silently inventing a cause.
    """
    text = str(stderr or "")
    if not text.strip():
        return ""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    informative = [line for line in lines if line and DIAGNOSTIC_LINE_PATTERN.search(line)]
    if informative:
        return informative[-1][:limit]
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    # Showing both boundaries exposes harness-side stderr truncation such as a
    # retained backend registry with the actual exception missing.
    left = max(1, (limit - 5) // 2)
    right = max(1, limit - 5 - left)
    return f"{compact[:left]} ... {compact[-right:]}"


def write_case_catalog_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Validation-only failure case catalog",
        "",
        "> Deterministic audit pointers, not additional observations or confirmed PyTorch bugs.",
        "",
        "| Baseline | Failure category | API group | API | JSONL line | Exit | Evidence / diagnostic | Raw SHA-256 |",
        "|---|---|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        if row["source_role"] != "campaign_checkpoint":
            continue
        evidence = str(row["evidence"]).replace("|", "\\|").replace("\n", " ")
        diagnostic = str(row.get("stderr_excerpt") or "").replace("|", "\\|").replace("\n", " ")
        detail = evidence if not diagnostic else f"{evidence}; stderr: {diagnostic}"
        api = str(row["api"]).replace("|", "\\|")
        lines.append(
            f"| {row['baseline']} | `{row['category']}` | `{row['api_group']}` | `{api}` | "
            f"{row['source_record_index']} | {row.get('exit_code', '')} | {detail} | "
            f"`{str(row['raw_output_sha256'])[:12]}` |"
        )
    lines += [
        "",
        "Use `source_sha256`, `source_record_index`, and the full `raw_output_sha256` in "
        "`failure_case_catalog.csv` to resolve each pointer against the immutable source snapshot.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if not rows and not fieldnames:
        raise ValueError(f"cannot infer columns for empty CSV {path}")
    fields = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def tex_escape(value: Any) -> str:
    text = str(value)
    for old, new in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"), ("&", r"\&")):
        text = text.replace(old, new)
    return text


def fmt_rate(value: float | None) -> str:
    return "--" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{100 * value:.1f}"


def fmt_rate_interval(numerator: int, denominator: int, low: float | None, high: float | None) -> str:
    if denominator <= 0 or low is None or high is None:
        return "--"
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f} [{100 * low:.1f}, {100 * high:.1f}])"


def write_latex(path: Path, summary: list[dict[str, Any]], coverage: list[dict[str, Any]]) -> None:
    baseline_rows = [r for r in summary if r["aggregation"] == "baseline"]
    lines = [
        "% AUTO-GENERATED; validation-only partial-checkpoint table.",
        "% Do not present as a completed benchmark result until coverage is complete.",
        r"\begin{table*}[t]",
        r"\centering\small",
        r"\caption{Validation-only generation failure analysis. Rates use known evidence only; $U$ is unknown.}",
        r"\label{tab:generation-failures-validation}",
        r"\begin{tabular}{lllrrrr}",
        r"\toprule",
        r"Source & Baseline & Failure mode & $N$ & Present & $U$ & Rate (\%) \\",
        r"\midrule",
    ]
    for row in baseline_rows:
        lines.append(
            "{} & {} & {} & {} & {} & {} & {} \\\\".format(
                tex_escape(row["source"]), tex_escape(row["baseline"]), tex_escape(row["category"]),
                row["n_total"], row["n_true"], row["n_unknown"], fmt_rate(row["failure_rate_known"]),
            )
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]

    overall = [r for r in coverage if r["api_group"] == "__ALL__"]
    lines += [
        r"\begin{table}[t]",
        r"\centering\small",
        r"\caption{Input coverage audit for the validation-only analysis.}",
        r"\label{tab:generation-failure-coverage}",
        r"\begin{tabular}{llrrr}",
        r"\toprule",
        r"Source & Baseline & Observed & Expected & Missing \\",
        r"\midrule",
    ]
    for row in overall:
        lines.append(
            "{} & {} & {} & {} & {} \\\\".format(
                tex_escape(row["source"]), row["baseline"], row["observed_records"],
                "--" if row["expected_records"] is None else row["expected_records"],
                "--" if row["missing_records"] is None else row["missing_records"],
            )
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_group_rate_latex(path: Path, rows: list[dict[str, Any]]) -> None:
    campaign = [
        row for row in rows
        if row["source_role"] in {"campaign_checkpoint", "campaign_combined"}
    ]
    indexed = {
        (row["source"], row["baseline"], row["api_group"], row["category"]): row
        for row in campaign
    }
    abbreviations = {
        "syntax_error": "Syntax",
        "wrong_or_missing_target_api": "Target",
        "missing_import": "Import",
        "shape_or_dtype_error": "Shape/dtype",
        "missing_oracle": "No oracle",
        "fake_assertion": "Fake oracle",
    }
    lines = [
        "% AUTO-GENERATED; validation-only baseline-by-API-group rates.",
        "% Cell: present/known (rate [Wilson 95% CI]), all values in percent.",
        "% Coverage must be complete before cross-baseline interpretation.",
    ]
    source_baselines = sorted({(row["source"], row["baseline"]) for row in campaign})
    for source, baseline in source_baselines:
        groups = sorted({row["api_group"] for row in campaign if row["source"] == source and row["baseline"] == baseline})
        lines += [
            r"\begin{table*}[t]",
            r"\centering\scriptsize",
            rf"\caption{{Validation-only {tex_escape(baseline)} error rates by API group. Cells are present/known (rate [Wilson 95\% CI]); coverage is observed/expected.}}",
            rf"\label{{tab:generation-group-rates-{tex_escape(baseline.lower())}}}",
            r"\setlength{\tabcolsep}{2.5pt}",
            r"\begin{tabular}{llrrrrrr}",
            r"\toprule",
            "API group & Coverage & " + " & ".join(abbreviations[c] for c in FOCAL_GROUP_CATEGORIES) + r" \\",
            r"\midrule",
        ]
        for group in groups:
            group_rows = [indexed[(source, baseline, group, category)] for category in FOCAL_GROUP_CATEGORIES]
            first = group_rows[0]
            expected = first["expected_records"]
            coverage_cell = f"{first['observed_records']}/{'--' if expected is None else expected}"
            cells = [
                fmt_rate_interval(
                    row["n_true"], row["n_known"], row["wilson_95_low"], row["wilson_95_high"]
                )
                for row in group_rows
            ]
            lines.append(f"{tex_escape(group)} & {coverage_cell} & " + " & ".join(cells) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_truncation_association_latex(path: Path, rows: list[dict[str, Any]]) -> None:
    campaign = [
        row for row in rows
        if row["source_role"] in {"campaign_checkpoint", "campaign_combined"}
    ]
    lines = [
        "% AUTO-GENERATED; validation-only descriptive association, not causal evidence.",
        r"\begin{table*}[t]",
        r"\centering\small",
        r"\caption{Within-baseline association of length truncation with parseability, oracle bearing, and standalone oracle reachability. Rates include Wilson 95\% intervals and do not imply causality.}",
        r"\label{tab:truncation-association-validation}",
        r"\begin{tabular}{lllrrrr}",
        r"\toprule",
        r"Baseline & Outcome & Coverage & Truncated & Not truncated & Risk difference & Unknown \\",
        r"\midrule",
    ]
    for row in campaign:
        expected = row["expected_records"]
        coverage_cell = f"{row['observed_records']}/{'--' if expected is None else expected}"
        truncated = fmt_rate_interval(
            row["truncated_outcome_positive"], row["truncated_n"],
            row["truncated_wilson_95_low"], row["truncated_wilson_95_high"],
        )
        nontruncated = fmt_rate_interval(
            row["nontruncated_outcome_positive"], row["nontruncated_n"],
            row["nontruncated_wilson_95_low"], row["nontruncated_wilson_95_high"],
        )
        difference = row["risk_difference_truncated_minus_nontruncated"]
        diff_cell = "--" if difference is None else f"{100 * difference:.1f}"
        unknown = row["unknown_truncation"] + row["unknown_outcome"]
        lines.append(
            f"{row['baseline']} & {tex_escape(row['outcome'])} & {coverage_cell} & "
            f"{truncated} & {nontruncated} & {diff_cell} & {unknown} \\\\"
        )
    lines += [
        r"\bottomrule", r"\end{tabular}",
        r"\begin{flushleft}\footnotesize Risk difference is truncated minus non-truncated within the same baseline. Missing denominators are shown as --. This partial-checkpoint analysis is descriptive, not causal, and does not support cross-model claims.\end{flushleft}",
        r"\end{table*}", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_markdown_report(
    path: Path, summary: list[dict[str, Any]], coverage: list[dict[str, Any]], sources: list[dict[str, Any]],
    integrity: list[dict[str, Any]], group_rates: list[dict[str, Any]],
    truncation_associations: list[dict[str, Any]], length_diagnostics: list[dict[str, Any]],
    harness_comparison: list[dict[str, Any]], campaign_metadata: dict[str, Any],
) -> None:
    smoke_guardrail = (
        "- Smoke-validation records are reported separately and are not pooled into campaign rates."
        if any(source["role"] == "smoke_validation" for source in sources)
        else "- No smoke-validation input is pooled into this checkpoint; campaign rates use only immutable seed shards."
    )
    lines = [
        "# Validation-only generation failure report",
        "",
        "> This is a partial-checkpoint validation artifact, not a completed benchmark result.",
        "",
        "## Input snapshots",
        "",
        "| Source | Role | Records | SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for source in sources:
        lines.append(f"| {source['label']} | {source['role']} | {source['records']} | `{source['sha256']}` |")
    lines += [
        "", "## Checkpoint scope", "",
        f"The rendered campaign tables pool {campaign_metadata['shard_count']} immutable seed shards "
        f"({sum(int(source['records']) for source in sources if source['role'] == 'campaign_checkpoint')} "
        "events). Their within-checkpoint denominator is "
        f"{campaign_metadata['expected_per_baseline']} records per baseline and "
        f"{campaign_metadata['expected_per_api_group']} per API group. The planned design has five "
        "seed shards, so this remains a diagnostic checkpoint rather than a final campaign result.",
        "", "## Ledger integrity", "",
        "| Source | Missing task ID | Duplicate task/baseline | Unexpected baseline | Run signatures | Seeds |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in integrity:
        lines.append(
            f"| {row['source']} | {row['missing_task_id_records']} | "
            f"{row['duplicate_task_baseline_records']} | {row['unexpected_baseline_records']} | "
            f"{len(row['run_signatures'])} | {len(row['generation_seeds'])} |"
        )
    lines += [
        "", "## Campaign coverage", "",
        "Coverage uses unique non-empty task IDs; raw, duplicate, and unidentified JSONL rows are shown separately.",
        "",
        "| Baseline | Raw | Unique tasks | Duplicate | Unidentified | Expected | Missing |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    campaign_coverage = [
        row for row in coverage
        if row["api_group"] == "__ALL__"
    ]
    for row in campaign_coverage:
        lines.append(
            f"| {row['baseline']} | {row['raw_records']} | {row['observed_records']} | "
            f"{row['duplicate_records']} | {row['unidentified_records']} | "
            f"{row['expected_records']} | {row['missing_records']} |"
        )
    lines += [
        "",
        "Baseline-by-API-group estimates, Wilson intervals, and row-specific coverage are in "
        "`campaign_combined_group_error_rates.csv`; the LaTeX rendering is "
        "`validation_group_rates.tex`.",
        "",
        "## Within-baseline truncation associations",
        "",
        "Cells are positive/eligible (rate [Wilson 95% CI]) in percent. Risk difference (RD) is "
        "truncated minus non-truncated. These are descriptive associations, not causal effects.",
        "",
        "| Baseline | Outcome | Coverage | Truncated | Not truncated | RD (pp) | Unknown |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in truncation_associations:
        expected = row["expected_records"]
        coverage_cell = f"{row['observed_records']}/{'--' if expected is None else expected}"
        truncated = fmt_rate_interval(
            row["truncated_outcome_positive"], row["truncated_n"],
            row["truncated_wilson_95_low"], row["truncated_wilson_95_high"],
        )
        nontruncated = fmt_rate_interval(
            row["nontruncated_outcome_positive"], row["nontruncated_n"],
            row["nontruncated_wilson_95_low"], row["nontruncated_wilson_95_high"],
        )
        difference = row["risk_difference_truncated_minus_nontruncated"]
        diff_cell = "--" if difference is None else f"{100 * difference:.1f}"
        unknown = row["unknown_truncation"] + row["unknown_outcome"]
        lines.append(
            f"| {row['baseline']} | `{row['outcome']}` | {coverage_cell} | {truncated} | "
            f"{nontruncated} | {diff_cell} | {unknown} |"
        )
    lines += [
        "",
        "## Finish-reason and length diagnostics",
        "",
        "Token and generation-time fields are descriptive harness telemetry; missing values are not imputed.",
        "",
        "| Baseline | Finish reason | N | Token known | Token min / median / p95 / max | Mean generation seconds |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in length_diagnostics:
        def number(value: Any, digits: int = 1) -> str:
            return "--" if value is None else f"{float(value):.{digits}f}"
        token_summary = " / ".join(
            number(row[name], 0) for name in ("tokens_min", "tokens_median", "tokens_p95", "tokens_max")
        )
        lines.append(
            f"| {row['baseline']} | `{row['finish_reason']}` | {row['n_records']} | "
            f"{row['n_token_count_known']} | {token_summary} | {number(row['generation_seconds_mean'], 2)} |"
        )
    lines += [
        "",
        "## Observed campaign failures and unknown evidence",
        "",
        "Rates below divide by known evidence only. Unknown observations remain in the `U` column.",
        "",
        "| Baseline | Failure mode | N | Present | U | Known-evidence rate |",
        "|---|---|---:|---:|---:|---:|",
    ]
    campaign_summary = [
        row for row in summary
        if row["aggregation"] == "baseline"
        and (row["n_true"] or row["n_unknown"])
    ]
    for row in campaign_summary:
        formatted_rate = fmt_rate(row["failure_rate_known"])
        rate_cell = formatted_rate if formatted_rate == "--" else f"{formatted_rate}%"
        lines.append(
            f"| {row['baseline']} | `{row['category']}` | {row['n_total']} | {row['n_true']} | "
            f"{row['n_unknown']} | {rate_cell} |"
        )
    lines += [
        "",
        "## Detector/harness consistency audit",
        "",
        "Only eligible, known labels enter the agreement denominator. This is a diagnostic comparison, not accuracy.",
        "",
        "| Baseline | Category | Comparable | Agree | Disagree | H+ / A- | H- / A+ | Harness U | Analyzer U |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in harness_comparison:
        if not row["n_disagree"]:
            continue
        lines.append(
            f"| {row['baseline']} | `{row['category']}` | {row['n_comparable']} | "
            f"{row['n_agree']} | {row['n_disagree']} | "
            f"{row['n_harness_true_analyzer_false']} | {row['n_harness_false_analyzer_true']} | "
            f"{row['n_harness_unknown']} | "
            f"{row['n_analyzer_unknown_given_harness_known']} |"
        )
    lines += [
        "",
        "All audit rows, including zero-disagreement signals, are in `detector_harness_comparison.csv`. "
        "Row-level pointers and canonicalized call evidence are in `detector_harness_disagreements.csv`. "
        "Disagreements require manual review; for example, the AST detector can resolve `F.*` aliases "
        "that a harness string matcher misses.",
        "",
        "## Interpretation guardrails",
        "",
        smoke_guardrail,
        "- A rate of `--` means there is no known denominator; it does not mean 0%.",
        "- The remaining planned seed shards must be completed before a final cross-baseline claim.",
        "- `missing_oracle` can be a baseline design property (not a PyTorch defect); interpret it as generated-test quality.",
        "- `target_not_executed` means the API call occurs only inside a function that the standalone script never invokes.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_paper_snippet(
    path: Path, summary: list[dict[str, Any]], coverage: list[dict[str, Any]],
    sources: list[dict[str, Any]], campaign_metadata: dict[str, Any],
) -> None:
    """Write conservative prose for Sections 4.3/4.7 of a partial run."""
    campaign_sources = [source for source in sources if source["role"] == "campaign_checkpoint"]
    campaign_records = sum(int(source["records"]) for source in campaign_sources)
    hash_prefixes = "+".join(source["sha256"][:12] for source in campaign_sources) or "unknown"
    expected_per_baseline = int(campaign_metadata.get("expected_per_baseline", 0))
    campaign_coverage = {
        row["baseline"]: row
        for row in coverage
        if row["api_group"] == "__ALL__"
    }
    campaign_summary = {
        (row["baseline"], row["category"]): row
        for row in summary
        if row["aggregation"] == "baseline"
    }

    def observed(baseline: str) -> int:
        return int(campaign_coverage.get(baseline, {}).get("observed_records", 0))

    def metric(baseline: str, category: str, field: str) -> int:
        return int(campaign_summary.get((baseline, category), {}).get(field, 0))

    def total_positive(category: str) -> int:
        return sum(metric(baseline, category, "n_true") for baseline in EXPECTED_BASELINES)

    b2_n = observed("B2")
    b2_parseable = metric("B2", "syntax_error", "n_false")
    b2_fake = metric("B2", "fake_assertion", "n_true")
    b2_uninvoked = metric("B2", "target_not_executed", "n_true")
    b1_wrong_target = metric("B1", "wrong_or_missing_target_api", "n_true")
    b1_shape_dtype = metric("B1", "shape_or_dtype_error", "n_true")
    missing_import_total = total_positive("missing_import")
    fake_verb = "contains" if b2_fake == 1 else "contain"
    uninvoked_verb = "places" if b2_uninvoked == 1 else "place"
    record_word = lambda count: "record" if count == 1 else "records"
    text = rf"""% AUTO-GENERATED from an immutable validation checkpoint.
% Intended insertion points: Sections 4.3 and 4.7. This is not a final result.
\paragraph{{Validation-checkpoint scope (Section 4.3).}}
The current generation-quality analysis pools {campaign_metadata.get('shard_count', 0)}
immutable campaign shards (SHA-256 prefixes \texttt{{{tex_escape(hash_prefixes)}}}),
containing {campaign_records} records. Coverage within these observed shards is
B0 {observed('B0')}/{expected_per_baseline},
B1 {observed('B1')}/{expected_per_baseline},
B2 {observed('B2')}/{expected_per_baseline}, and
B3 {observed('B3')}/{expected_per_baseline} unique tasks. The planned design has
five seed shards; consequently, these data validate the logging and classification
pipeline but do not support a cross-baseline effectiveness claim.  The taxonomy records
syntax and target-API failures; missing imports; shape/dtype, index/bounds,
undefined-name, argument-signature, dependency-import, setup/environment,
resource-exhaustion, assertion, other-runtime, timeout, and nondeterministic failures;
missing or fake oracles; broad exception swallowing; target calls placed only
inside uninvoked functions; and length-truncated generations.  Every label is
tri-state, and rates exclude unknown observations while reporting their count.

\paragraph{{Generation-failure cases (Section 4.7).}}
Within the currently observed B2 slice ($N={b2_n}$),
{metric('B2', 'syntax_error', 'n_true')} generations are syntactically invalid
and {metric('B2', 'truncated_generation', 'n_true')} end at the decoding length
limit.  Among the {b2_parseable} syntactically valid B2 records,
{b2_fake} {fake_verb} a recognized fake assertion
and {b2_uninvoked} {uninvoked_verb} the requested API only
inside a function that the standalone subprocess never invokes.  The latter
explains why an exit code of zero alone is insufficient evidence of a valid
test.  B0 and B1 currently contain
{metric('B0', 'missing_oracle', 'n_true')}/{observed('B0')} and
{metric('B1', 'missing_oracle', 'n_true')}/{observed('B1')} records without a
recognized executable oracle, respectively; this is a generated-test quality
property and not evidence of a PyTorch defect.  In the observed B1 slice,
{b1_wrong_target} {record_word(b1_wrong_target)} omit the requested target API
and {b1_shape_dtype} {record_word(b1_shape_dtype)} have a recorded shape/dtype
runtime diagnostic.  Across the current checkpoint, {missing_import_total}
{record_word(missing_import_total)} have positive
missing-import evidence; this observed count does not establish absence in
unfinished slices.  All figures in this paragraph are validation-checkpoint
counts and must be regenerated after campaign completion before comparative
interpretation.
"""
    path.write_text(text, encoding="utf-8")


def analyze(
    inputs: list[Path], output_dir: Path, expected_per_baseline: int = 120, expected_per_group: int = 12
) -> dict[str, Any]:
    if expected_per_baseline <= 0 or expected_per_group <= 0:
        raise ValueError("expected record counts must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    classified: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    used_labels: Counter[str] = Counter()
    for path in inputs:
        records, meta = load_source(path)
        used_labels[meta["label"]] += 1
        if used_labels[meta["label"]] > 1:
            meta["label"] += f"_{used_labels[meta['label']]}"
        sources.append(meta)
        for record in records:
            statuses, evidence = classify_record(record)
            classified.append({
                "source": meta["label"],
                "source_role": meta["role"],
                "source_sha256": meta["sha256"],
                "source_record_index": record["_source_record_index"],
                "run_signature": record.get("run_signature"),
                "task_id": record.get("task_id"),
                "raw_output_sha256": record.get("raw_output_sha256"),
                "baseline": record.get("baseline") or "__UNKNOWN__",
                "api_group": record.get("api_group") or "__UNKNOWN__",
                "api": record.get("api") or "__UNKNOWN__",
                "generation_seed": record.get("generation_seed"),
                "finish_reason": record.get("finish_reason"),
                "raw_token_count": record.get("raw_token_count"),
                "generation_seconds": record.get("generation_seconds"),
                "subprocess_seconds": record.get("subprocess_seconds"),
                "exit_code": record.get("exit_code"),
                "stderr_excerpt": (
                    diagnostic_excerpt(record.get("stderr"))
                    if isinstance(record.get("exit_code"), int) and record.get("exit_code") != 0 else ""
                ),
                "harness_expected": harness_expected_labels(record),
                **statuses,
                "evidence": evidence,
            })

    summary = summarize(classified)
    coverage = coverage_rows(classified, sources, expected_per_baseline, expected_per_group)
    group_rates = group_error_rate_rows(summary, coverage)
    truncation_associations = truncation_association_rows(classified, coverage)
    length_diagnostics = length_diagnostic_rows(classified, coverage)
    seed_telemetry = seed_telemetry_rows(classified)
    integrity = integrity_rows(classified, sources)
    harness_comparison = harness_comparison_rows(classified)
    harness_disagreements = harness_disagreement_rows(classified)
    case_catalog = case_catalog_rows(classified)
    combined_summary, combined_coverage, combined_group_rates, combined_metadata = combined_campaign_view(
        classified, expected_per_baseline, expected_per_group
    )
    combined_classified = campaign_combined_records(classified)
    combined_truncation_associations = truncation_association_rows(
        combined_classified, combined_coverage
    )
    combined_length_diagnostics = length_diagnostic_rows(combined_classified, combined_coverage)
    combined_harness_comparison = harness_comparison_rows(combined_classified)
    event_rows = []
    for item in classified:
        row = {k: v for k, v in item.items() if k not in {"evidence", "harness_expected"}}
        row["harness_expected_json"] = json.dumps(
            item["harness_expected"], ensure_ascii=False, sort_keys=True
        )
        row["evidence_json"] = json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True)
        event_rows.append(row)

    event_fields = [
        "source", "source_role", "source_sha256", "source_record_index", "run_signature", "task_id",
        "baseline", "api_group", "api", "generation_seed", "finish_reason", "raw_token_count",
        "generation_seconds", "subprocess_seconds", "exit_code", "stderr_excerpt",
        "raw_output_sha256", *CATEGORIES,
        "harness_expected_json", "evidence_json",
    ]
    write_csv(output_dir / "event_classification.csv", event_rows, event_fields)
    with (output_dir / "event_classification.jsonl").open("w", encoding="utf-8") as handle:
        for item in classified:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    write_csv(output_dir / "failure_summary.csv", summary)
    write_csv(output_dir / "coverage_summary.csv", coverage)
    (output_dir / "failure_summary.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": summary}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "coverage_summary.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": coverage}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    combined_summary_fields = [
        "aggregation", "source", "source_role", "generation_seed", "baseline", "api_group", "category",
        "n_total", "n_known", "n_true", "n_false", "n_unknown", "failure_rate_known",
        "failure_rate_total_lower_bound",
    ]
    combined_coverage_fields = [
        "source", "source_role", "baseline", "api_group", "raw_records", "observed_records",
        "duplicate_records", "unidentified_records", "expected_records", "missing_records", "coverage_rate",
    ]
    combined_group_rate_fields = [
        "source", "source_role", "baseline", "api_group", "category", "n_total", "n_known",
        "n_true", "n_false", "n_unknown", "failure_rate_known", "wilson_95_low", "wilson_95_high",
        "observed_records", "raw_records", "duplicate_records", "unidentified_records",
        "expected_records", "missing_records", "coverage_rate",
    ]
    write_csv(
        output_dir / "campaign_combined_failure_summary.csv", combined_summary, combined_summary_fields
    )
    (output_dir / "campaign_combined_failure_summary.json").write_text(
        json.dumps(
            {"schema_version": VERSION, "metadata": combined_metadata, "rows": combined_summary},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(output_dir / "campaign_combined_coverage.csv", combined_coverage, combined_coverage_fields)
    (output_dir / "campaign_combined_coverage.json").write_text(
        json.dumps(
            {"schema_version": VERSION, "metadata": combined_metadata, "rows": combined_coverage},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(
        output_dir / "campaign_combined_group_error_rates.csv",
        combined_group_rates,
        combined_group_rate_fields,
    )
    (output_dir / "campaign_combined_group_error_rates.json").write_text(
        json.dumps(
            {"schema_version": VERSION, "metadata": combined_metadata, "rows": combined_group_rates},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(output_dir / "group_error_rates.csv", group_rates)
    (output_dir / "group_error_rates.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": group_rates}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(output_dir / "truncation_associations.csv", truncation_associations)
    (output_dir / "truncation_associations.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": truncation_associations}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(output_dir / "length_diagnostics.csv", length_diagnostics)
    (output_dir / "length_diagnostics.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": length_diagnostics}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(output_dir / "seed_telemetry.csv", seed_telemetry)
    (output_dir / "seed_telemetry.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": seed_telemetry}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "input_integrity.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": integrity}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(output_dir / "detector_harness_comparison.csv", harness_comparison)
    (output_dir / "detector_harness_comparison.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": harness_comparison}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    disagreement_fields = [
        "source", "source_role", "source_sha256", "source_record_index", "baseline", "category",
        "harness_label", "analyzer_label", "task_id", "api_group", "api", "generation_seed",
        "raw_output_sha256", "analyzer_evidence",
    ]
    write_csv(
        output_dir / "detector_harness_disagreements.csv", harness_disagreements, disagreement_fields
    )
    (output_dir / "detector_harness_disagreements.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": harness_disagreements}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        output_dir / "failure_case_catalog.csv",
        case_catalog,
        [
            "source", "source_role", "source_sha256", "source_record_index", "baseline", "category",
            "task_id", "api_group", "api", "generation_seed", "exit_code", "stderr_excerpt",
            "raw_output_sha256", "evidence",
        ],
    )
    (output_dir / "failure_case_catalog.json").write_text(
        json.dumps({"schema_version": VERSION, "rows": case_catalog}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_case_catalog_markdown(output_dir / "failure_case_catalog.md", case_catalog)
    write_latex(output_dir / "validation_tables.tex", combined_summary, combined_coverage)
    write_group_rate_latex(output_dir / "validation_group_rates.tex", combined_group_rates)
    write_truncation_association_latex(
        output_dir / "validation_truncation_associations.tex", combined_truncation_associations
    )
    write_markdown_report(
        output_dir / "validation_report.md", combined_summary, combined_coverage, sources, integrity,
        combined_group_rates, combined_truncation_associations, combined_length_diagnostics,
        combined_harness_comparison, combined_metadata,
    )
    write_paper_snippet(
        output_dir / "paper_integration_snippet.tex", combined_summary, combined_coverage,
        sources, combined_metadata,
    )

    manifest = {
        "schema_version": VERSION,
        "analyzer_sha256": LOADED_ANALYZER_SHA256,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "classification_semantics": {
            "true": "failure mode positively identified",
            "false": "available evidence rules out the failure mode",
            "null": "unknown; evidence cannot distinguish present from absent",
            "rate_denominator": "n_known = n_true + n_false",
            "interval": "two-sided Wilson 95%; null when denominator is zero",
            "truncation_association": "within-source and within-baseline descriptive association; not causal",
            "length_quantiles": "nearest-rank empirical median and p95 over known raw_token_count values",
            "throughput": "descriptive only; computed from records with known token counts and positive generation duration; missing telemetry is not imputed",
            "harness_comparison": "agreement audit only; neither detector nor harness field is treated as ground truth",
            "smoke_policy": "smoke-validation records are reported separately and never pooled into campaign rates",
        },
        "categories": list(CATEGORIES),
        "expected_campaign_records_per_baseline": expected_per_baseline,
        "expected_campaign_records_per_api_group": expected_per_group,
        "sources": sources,
        "input_integrity": integrity,
        "detector_harness_comparison": harness_comparison,
        "detector_harness_disagreement_records": len(harness_disagreements),
        "campaign_combined": combined_metadata,
        "rendered_campaign_view": "campaign_combined",
        "representative_failure_cases": len(case_catalog),
        "classified_records": len(classified),
        "outputs": [
            "event_classification.csv", "event_classification.jsonl", "failure_summary.csv",
            "failure_summary.json", "coverage_summary.csv", "coverage_summary.json", "validation_tables.tex",
            "campaign_combined_failure_summary.csv", "campaign_combined_failure_summary.json",
            "campaign_combined_coverage.csv", "campaign_combined_coverage.json",
            "campaign_combined_group_error_rates.csv", "campaign_combined_group_error_rates.json",
            "group_error_rates.csv", "group_error_rates.json", "truncation_associations.csv",
            "truncation_associations.json", "length_diagnostics.csv", "length_diagnostics.json",
            "seed_telemetry.csv", "seed_telemetry.json",
            "validation_group_rates.tex",
            "validation_truncation_associations.tex",
            "input_integrity.json", "detector_harness_comparison.csv", "detector_harness_comparison.json",
            "detector_harness_disagreements.csv", "detector_harness_disagreements.json",
            "failure_case_catalog.csv", "failure_case_catalog.json", "failure_case_catalog.md",
            "validation_report.md",
            "paper_integration_snippet.tex",
        ],
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path, help="JSONL ledger (repeatable)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-records-per-baseline", type=int, default=120)
    parser.add_argument("--expected-records-per-group", type=int, default=12)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = analyze(
        args.input, args.output_dir, args.expected_records_per_baseline, args.expected_records_per_group
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
