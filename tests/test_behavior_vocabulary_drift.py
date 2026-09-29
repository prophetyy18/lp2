"""Does the Card template still list the behavior vocabulary the loader accepts?

Two vocabularies exist: `BEHAVIOR_UNITS` / `BEHAVIOR_TIMEZONES` in the model,
which the loader enforces, and the `<a | b | c>` line in
`CAPABILITY_CARD.template.md`, which an author copies. Nothing connected them,
so the template drifted twice without anything failing:

  - it listed `q64_128`, a fixed-point encoding V4 does not have, while
    naming a nonexistent thing in a controlled vocabulary is worse than
    omitting it — the loader would accept the unit and no code would know
    what it meant;
  - it omitted `timezone` entirely, so the one field a consumer hits first
    ("is this `2024-01-02T21:00+00:00` or a bare `2024-01-02 16:00`?") was not
    something a Card could even state.

Both are the same defect as a stale comment: the copy is not checked against
the thing it copies. A vocabulary a Card cannot express is a promise the
template quietly fails to ask for.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from framework.architecture.model import (
    BEHAVIOR_ORDERING,
    BEHAVIOR_TIME,
    BEHAVIOR_TIMEZONES,
    BEHAVIOR_UNITS,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "implement" / "templates" / "CAPABILITY_CARD.template.md"

# The empty string means "not specified" and is never written in a template.
CHOICES = {
    "unit": BEHAVIOR_UNITS,
    "time": BEHAVIOR_TIME,
    "timezone": BEHAVIOR_TIMEZONES,
    "ordering": BEHAVIOR_ORDERING,
}


def _offered(line: str) -> set[str]:
    """The alternatives between the angle brackets on a template line."""
    inner = re.search(r"<([^>]+)>", line)
    if not inner:
        return set()
    return {v.strip() for v in inner.group(1).split("|")}


class TemplateVocabularyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lines = TEMPLATE.read_text(encoding="utf-8").splitlines()

    def _line_for(self, field: str) -> str:
        for line in self.lines:
            if line.strip().startswith(f"{field}:"):
                return line
        self.fail(f"CAPABILITY_CARD.template.md has no `{field}:` line")

    def test_template_offers_exactly_the_loader_vocabulary(self) -> None:
        for field, vocabulary in CHOICES.items():
            with self.subTest(field=field):
                expected = set(vocabulary) - {""}
                self.assertEqual(
                    _offered(self._line_for(field)),
                    expected,
                    f"the template's `{field}` line does not match "
                    f"{field} vocabulary in framework/architecture/model.py",
                )

    def test_every_encoding_the_template_names_is_one_v4_has(self) -> None:
        """`q64_128` was listed but does not exist. V4 has exactly two
        fixed-point encodings, and both are named by their on-chain field.
        """
        encodings = {
            v for v in _offered(self._line_for("unit")) if re.fullmatch(r"q\d+_\d+", v)
        }
        self.assertEqual(encodings, {"q64_96", "q128_128"})

    def test_the_timezone_field_is_present(self) -> None:
        # A Card must be able to say what shape a returned time value is in.
        # Without this the field is unaskable, and the confusion it causes is
        # the one `behavior.timezone` was added to prevent.
        self.assertIn("tz_aware_utc", _offered(self._line_for("timezone")))


if __name__ == "__main__":
    unittest.main()
