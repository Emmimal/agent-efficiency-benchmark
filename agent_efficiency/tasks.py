"""Ten tiny repositories, each with one seeded bug and a real unittest suite.

Every task defines:
  * the buggy source file (app/core.py) and its tests,
  * `fix`       - the correct edit (the reference solution),
  * `wrong_fix` - a plausible but wrong edit inside the right file,
and shares a set of DECOYS: harmless edits to files that have nothing to do
with the bug (the "wrong file" failure mode).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Edit:
    """A reversible string replacement in one file."""

    path: str
    old: str
    new: str

    def reversed(self) -> "Edit":
        return Edit(self.path, self.new, self.old)

    @property
    def key(self) -> str:
        digest = hashlib.sha1(f"{self.old}\0{self.new}".encode()).hexdigest()[:8]
        return f"{self.path}|{digest}"


UTILS = '''"""Small shared helpers."""


def clamp(x, lo, hi):
    return max(lo, min(x, hi))


def label(name):
    return "<" + name + ">"
'''

CONFIG = '''"""Application settings."""

DEBUG = False
MAX_ITEMS = 100
'''

# Plausible-looking edits that cannot affect the tests (wrong-file / overwork).
DECOYS = (
    Edit("app/config.py", "MAX_ITEMS = 100", "MAX_ITEMS = 250"),
    Edit("app/utils.py", "return max(lo, min(x, hi))", "return min(hi, max(x, lo))"),
    Edit("app/utils.py", 'return "<" + name + ">"', 'return "[" + name + "]"'),
)

CORE_PATH = "app/core.py"


@dataclass(frozen=True)
class Task:
    name: str
    core: str
    test: str
    fix: Edit
    wrong_fix: Edit

    @property
    def cosmetic(self) -> Edit:
        """A pointless but harmless edit inside the correct file (adds a docstring)."""
        first = self.core.split("\n", 1)[0] + "\n"
        return Edit(CORE_PATH, first, first + '    """Compute the result."""\n')

    def reference_diff(self) -> int:
        """Lines added + removed by the reference fix."""
        from .repo import line_delta
        a, r = line_delta(self.core, self.core.replace(self.fix.old, self.fix.new, 1))
        return a + r

    def files(self) -> dict[str, str]:
        return {
            "app/__init__.py": "",
            "app/core.py": self.core,
            "app/utils.py": UTILS,
            "app/config.py": CONFIG,
            "tests/__init__.py": "",
            "tests/test_core.py": self.test,
        }


def _task(name, core, test, fix, wrong):
    return Task(
        name=name,
        core=core,
        test=test,
        fix=Edit(CORE_PATH, *fix),
        wrong_fix=Edit(CORE_PATH, *wrong),
    )


TASKS: tuple[Task, ...] = (
    _task(
        "off_by_one_range",
        '''def sum_to_n(n):
    total = 0
    for i in range(1, n):
        total += i
    return total
''',
        '''import unittest
from app.core import sum_to_n


class SumToN(unittest.TestCase):
    def test_small(self):
        self.assertEqual(sum_to_n(4), 10)

    def test_one(self):
        self.assertEqual(sum_to_n(1), 1)

    def test_zero(self):
        self.assertEqual(sum_to_n(0), 0)
''',
        ("range(1, n):", "range(1, n + 1):"),
        ("range(1, n):", "range(2, n):"),
    ),
    _task(
        "boundary_comparison",
        '''def is_adult(age):
    return age > 18
''',
        '''import unittest
from app.core import is_adult


class IsAdult(unittest.TestCase):
    def test_boundary(self):
        self.assertTrue(is_adult(18))

    def test_older(self):
        self.assertTrue(is_adult(30))

    def test_younger(self):
        self.assertFalse(is_adult(10))
''',
        ("age > 18", "age >= 18"),
        ("age > 18", "age < 18"),
    ),
    _task(
        "empty_list_crash",
        '''def average(xs):
    return sum(xs) / len(xs)
''',
        '''import unittest
from app.core import average


class Average(unittest.TestCase):
    def test_values(self):
        self.assertEqual(average([2, 4, 6]), 4)

    def test_empty(self):
        self.assertEqual(average([]), 0.0)
''',
        (
            "    return sum(xs) / len(xs)\n",
            "    if not xs:\n        return 0.0\n    return sum(xs) / len(xs)\n",
        ),
        ("return sum(xs) / len(xs)", "return sum(xs) // len(xs)"),
    ),
    _task(
        "wrong_formula",
        '''def apply_discount(price, pct):
    return price * pct / 100
''',
        '''import unittest
from app.core import apply_discount


class Discount(unittest.TestCase):
    def test_ten_percent(self):
        self.assertEqual(apply_discount(200, 10), 180)

    def test_zero(self):
        self.assertEqual(apply_discount(50, 0), 50)
''',
        ("return price * pct / 100", "return price - price * pct / 100"),
        ("return price * pct / 100", "return price * (100 - pct)"),
    ),
    _task(
        "missing_strip",
        '''def normalize(s):
    return s.lower()
''',
        '''import unittest
from app.core import normalize


class Normalize(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(normalize("  Hello "), "hello")

    def test_upper(self):
        self.assertEqual(normalize("ABC"), "abc")
''',
        ("return s.lower()", "return s.strip().lower()"),
        ("return s.lower()", "return s.title()"),
    ),
    _task(
        "order_lost",
        '''def dedupe(xs):
    return list(set(xs))
''',
        '''import unittest
from app.core import dedupe


class Dedupe(unittest.TestCase):
    def test_order_kept(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_empty(self):
        self.assertEqual(dedupe([]), [])
''',
        ("return list(set(xs))", "return list(dict.fromkeys(xs))"),
        ("return list(set(xs))", "return sorted(set(xs))"),
    ),
    _task(
        "slice_off_by_one",
        '''def last_n(xs, n):
    return xs[-n - 1:]
''',
        '''import unittest
from app.core import last_n


class LastN(unittest.TestCase):
    def test_two(self):
        self.assertEqual(last_n([1, 2, 3, 4], 2), [3, 4])

    def test_one(self):
        self.assertEqual(last_n([1], 1), [1])
''',
        ("xs[-n - 1:]", "xs[-n:]"),
        ("xs[-n - 1:]", "xs[-n + 1:]"),
    ),
    _task(
        "wrong_variable",
        '''def area(w, h):
    return w * w
''',
        '''import unittest
from app.core import area


class Area(unittest.TestCase):
    def test_rect(self):
        self.assertEqual(area(3, 4), 12)

    def test_square(self):
        self.assertEqual(area(5, 5), 25)
''',
        ("return w * w", "return w * h"),
        ("return w * w", "return w + h"),
    ),
    _task(
        "branch_order",
        '''def fizzbuzz(n):
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    if n % 15 == 0:
        return "FizzBuzz"
    return str(n)
''',
        '''import unittest
from app.core import fizzbuzz


class FizzBuzz(unittest.TestCase):
    def test_fifteen(self):
        self.assertEqual(fizzbuzz(15), "FizzBuzz")

    def test_three(self):
        self.assertEqual(fizzbuzz(9), "Fizz")

    def test_five(self):
        self.assertEqual(fizzbuzz(10), "Buzz")

    def test_other(self):
        self.assertEqual(fizzbuzz(7), "7")
''',
        (
            'if n % 3 == 0:\n        return "Fizz"\n    if n % 5 == 0:\n'
            '        return "Buzz"\n    if n % 15 == 0:\n        return "FizzBuzz"\n',
            'if n % 15 == 0:\n        return "FizzBuzz"\n    if n % 3 == 0:\n'
            '        return "Fizz"\n    if n % 5 == 0:\n        return "Buzz"\n',
        ),
        ("if n % 3 == 0:", "if n % 3 == 0 and n < 15:"),
    ),
    _task(
        "split_whitespace",
        '''def count_words(text):
    return len(text.split(" "))
''',
        '''import unittest
from app.core import count_words


class CountWords(unittest.TestCase):
    def test_double_space(self):
        self.assertEqual(count_words("a b  c"), 3)

    def test_single(self):
        self.assertEqual(count_words("one"), 1)
''',
        ('text.split(" ")', "text.split()"),
        ('text.split(" ")', 'text.split(",")'),
    ),
)

TASKS_BY_NAME = {t.name: t for t in TASKS}
