"""Is the provenance method still reachable, or has the wiring rotted?

This cannot test that an agent will read the method. Nothing can — a document
sitting on disk is read when its reader happens to suspect there is a problem,
and the whole failure mode here is that nothing looks wrong.

What it *can* test is the realistic decay: a pointer getting trimmed out during
an unrelated edit, leaving the method fully written and unreachable. The
walk itself now loads from `.claude/rules/` on a `paths:` match, so the
pointer that matters is CLAUDE.md's sentence saying so — and the moment that
goes stale, the mechanism becomes invisible without anything failing.

So this asserts reachability as a structure, and is honest that it is a
structure check and not a behavioural one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
AGENTS_MD = ROOT / "AGENTS.md"
METHOD = ROOT / "docs" / "design" / "DECLARATION-PROVENANCE.md"
ROLES = sorted((ROOT / ".claude" / "agents").glob("*.md"))


class MethodReachabilityTests(unittest.TestCase):
    """The method exists, the always-loaded files still point at it, and the
    path-gated rule that carries the walk is where the walk is."""

    def test_the_method_exists(self) -> None:
        self.assertTrue(METHOD.is_file(), f"{METHOD} is missing")
        self.assertGreater(len(METHOD.read_text(encoding="utf-8")), 2000)

    def test_claude_md_points_at_the_method(self) -> None:
        # CLAUDE.md and AGENTS.md are both loaded into every session. If this
        # reference goes from both, the method is unreachable by default.
        self.assertIn("DECLARATION-PROVENANCE.md", CLAUDE_MD.read_text(encoding="utf-8"))

    def test_the_method_is_pointed_at_from_the_architecture_role(self) -> None:
        # ac-designer is the role that investigates blockers, and "this
        # capability should not exist" is the answer most likely to be missed
        # by a role whose job is to extend the architecture.
        ac = (ROOT / ".claude" / "agents" / "ac-designer.md").read_text(encoding="utf-8")
        self.assertIn("DECLARATION-PROVENANCE.md", ac)

    def test_claude_md_states_the_principle_not_just_the_link(self) -> None:
        """The operative idea must be present, not only a path to it.

        It used to live inline in CLAUDE.md. It now lives in
        `.claude/rules/declaration-provenance.md`, which loads on `paths:`
        match — so an agent that opens anything under `architecture/` or
        `docs/implement/` gets the principle without a second lookup and
        without every unrelated turn paying for it. What is being tested is
        unchanged: the principle is reachable by the time it can matter, and
        CLAUDE.md says so rather than leaving a reader to find the mechanism.
        """
        def flat(p: Path) -> str:
            # A literal phrase against wrapped prose is brittle: rewrap the
            # line and a correct file goes red, which teaches the next editor
            # the rule is optional.
            return re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))

        rule = ROOT / ".claude" / "rules" / "declaration-provenance.md"
        self.assertTrue(rule.is_file(), f"{rule} is missing")
        self.assertIn("Existence is a hypothesis", flat(rule))

        self.assertIn(
            "Existence is a hypothesis", flat(CLAUDE_MD),
            "CLAUDE.md must still name the principle, or an agent that only "
            "reads CLAUDE.md cannot tell that a declaration is a claim",
        )
        self.assertIn(
            "loaded automatically", flat(CLAUDE_MD),
            "CLAUDE.md must say the walk is loaded on the paths it applies to, "
            "otherwise the pointer is no better than the inline copy it replaced",
        )

    def test_the_automated_parts_are_actually_automated(self) -> None:
        """The method claims two of its checks are mechanical and therefore
        run by `validate` on every change. If those findings stop being
        reported, the claim is false and the method is overstating itself.
        """
        from framework.architecture import validator
        from framework.architecture.loader import load
        from framework.architecture.errors import SCHEMA_DANGLING

        codes = {f.code for f in validator.validate(load(ROOT))}
        self.assertIn(
            SCHEMA_DANGLING, codes,
            "the method says a dangling schema ref is caught automatically; "
            "it is not being caught any more",
        )

    def test_no_role_document_points_at_a_method_that_moved(self) -> None:
        """Any role that names a doc under docs/design/ must name one that
        exists, so a moved file cannot leave a role citing nothing.
        """
        for role in ROLES:
            for ref in set(re.findall(r"docs/design/[A-Z0-9_-]+\.md",
                                      role.read_text(encoding="utf-8"))):
                with self.subTest(role=role.name, ref=ref):
                    self.assertTrue((ROOT / ref).is_file(), f"{role.name} cites {ref}, "
                                    f"which does not exist")


if __name__ == "__main__":
    unittest.main()
