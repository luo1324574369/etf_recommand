"""在独立进程中试运行候选因子，不接触正式因子注册表。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


_FORBIDDEN_NAMES = {
    "__builtins__", "__import__", "breakpoint", "compile", "eval", "exec",
    "globals", "input", "locals", "open", "vars",
}
@dataclass(frozen=True)
class SandboxResult:
    values: list
    source_hash: str


class FactorSandbox:
    def __init__(self, timeout_seconds: float = 5.0, max_source_chars: int = 50_000):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_source_chars = max_source_chars

    def run(self, source: str, rows: list[dict]) -> SandboxResult:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self._validate_source(source)
        if not isinstance(rows, list):
            raise TypeError("sandbox rows must be a list")

        with tempfile.TemporaryDirectory(prefix="factor-sandbox-") as directory:
            root = Path(directory)
            source_path = root / "candidate.py"
            input_path = root / "input.json"
            source_path.write_text(source, encoding="utf-8")
            input_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            source_path.chmod(0o444)
            input_path.chmod(0o444)
            command = [
                sys.executable,
                "-I",
                "-S",
                "-c",
                self._runner_script(),
                str(source_path),
                str(input_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    env={"PATH": os.environ.get("PATH", "")},
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise TimeoutError(
                    f"factor sandbox exceeded {self.timeout_seconds:.2f}s"
                ) from error

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "candidate process failed"
            raise RuntimeError(f"factor sandbox failed: {detail}")
        try:
            payload = json.loads(completed.stdout)
            values = payload["values"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError("factor sandbox returned invalid JSON") from error
        if not isinstance(values, list):
            raise RuntimeError("factor sandbox result must be a list")
        for value in values:
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("factor sandbox values must be finite numbers or null")
        return SandboxResult(values=values, source_hash=source_hash)

    def _validate_source(self, source: str) -> None:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("factor source must not be empty")
        if len(source) > self.max_source_chars:
            raise ValueError("factor source is too large")
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as error:
            raise ValueError(f"factor source has invalid syntax: {error}") from error
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                raise ValueError("factor source cannot import modules or mutate globals")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                raise ValueError(f"factor source uses forbidden name: {node.id}")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise ValueError("factor source cannot access dunder attributes")
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if len(functions) != 1 or functions[0].name not in {"calculate", "factor"}:
            raise ValueError("factor source must define exactly one calculate(row) function")

    @staticmethod
    def _runner_script() -> str:
        return """
import json
import sys

source_path, input_path = sys.argv[1:]
source = open(source_path, encoding='utf-8').read()
namespace = {'__builtins__': {
    'abs': abs, 'all': all, 'any': any, 'float': float, 'int': int,
    'len': len, 'max': max, 'min': min, 'round': round, 'sum': sum,
}}
exec(compile(source, source_path, 'exec'), namespace, namespace)
function = namespace.get('calculate') or namespace.get('factor')
rows = json.load(open(input_path, encoding='utf-8'))
values = [function(row) for row in rows]
json.dump({'values': values}, sys.stdout, ensure_ascii=False)
"""
