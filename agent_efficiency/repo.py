"""A real on-disk repository. Everything here is genuine: files are written
to a temp directory, tests run in a subprocess, diffs are computed from the
actual file contents. Only the *decisions* come from the simulated agent.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .tasks import Edit, Task

TEST_COMMAND = "python -m unittest discover -s tests -t ."

# Test results are a pure function of (task, file contents), so identical
# states are executed once per process and re-used afterwards. Disable with
# Repo(..., use_cache=False) to force a subprocess on every run.
_TEST_CACHE: dict[tuple[str, str], tuple[int, str]] = {}


def sha(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def line_delta(old: str, new: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


@dataclass(frozen=True)
class EditResult:
    changed: bool
    added: int = 0
    removed: int = 0


class Repo:
    def __init__(self, task: Task, root: str | Path, use_cache: bool = True):
        self.task = task
        self.root = Path(root)
        self.use_cache = use_cache
        self.initial = task.files()
        self.current = dict(self.initial)
        for rel, text in self.initial.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    # ---- state -----------------------------------------------------------
    def state_hash(self) -> str:
        h = hashlib.sha1()
        for rel in sorted(self.current):
            h.update(rel.encode())
            h.update(b"\0")
            h.update(self.current[rel].encode())
            h.update(b"\0")
        return h.hexdigest()[:12]

    def read(self, rel: str) -> str:
        return self.current[rel]

    def relevant_files(self) -> set[str]:
        """Files the test suite imports from `app` (what a harness can infer
        without knowing the answer)."""
        found: set[str] = set()
        for rel, text in self.initial.items():
            if rel.startswith("tests/") and rel.endswith(".py"):
                for mod in re.findall(r"^from (app(?:\.\w+)+) import", text, re.M):
                    found.add(mod.replace(".", "/") + ".py")
        return found

    # ---- edits -----------------------------------------------------------
    def apply(self, edit: Edit) -> EditResult:
        text = self.current.get(edit.path)
        if text is None or edit.old not in text:
            return EditResult(False)
        new_text = text.replace(edit.old, edit.new, 1)
        if new_text == text:
            return EditResult(False)
        (self.root / edit.path).write_text(new_text)
        self.current[edit.path] = new_text
        added, removed = line_delta(text, new_text)
        return EditResult(True, added, removed)

    def diff_text(self) -> str:
        parts = []
        for rel in sorted(self.current):
            if self.current[rel] != self.initial[rel]:
                parts.extend(
                    difflib.unified_diff(
                        self.initial[rel].splitlines(),
                        self.current[rel].splitlines(),
                        f"a/{rel}",
                        f"b/{rel}",
                        lineterm="",
                    )
                )
        return "\n".join(parts)

    def final_diff(self) -> tuple[int, int, list[str]]:
        added = removed = 0
        files = []
        for rel in sorted(self.current):
            if self.current[rel] != self.initial[rel]:
                a, r = line_delta(self.initial[rel], self.current[rel])
                added, removed = added + a, removed + r
                files.append(rel)
        return added, removed, files

    # ---- tests -----------------------------------------------------------
    def run_tests(self) -> tuple[int, str]:
        """Return (exit_code, normalised_output_hash)."""
        key = (self.task.name, self.state_hash())
        if self.use_cache and key in _TEST_CACHE:
            return _TEST_CACHE[key]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
            code, out = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            code, out = 124, "timeout"
        for root in {str(self.root), str(self.root.resolve())}:
            out = out.replace(root, "<repo>")
        out = re.sub(r"in \d+\.\d+s", "in <t>s", out)
        result = (code, sha(out))
        if self.use_cache:
            _TEST_CACHE[key] = result
        return result
