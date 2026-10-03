"""The always-injected instruction surface, and the partition between its parts.

`CLAUDE.md` and `AGENTS.md` are both loaded into every session and inherited by
every subagent (verified against the 2.1.284 binary: `claude-md-and-agents-md`
loads AGENTS.md *beside* CLAUDE.md, and the Agent tool injects the loaded
CLAUDE.md hierarchy into subagents). That makes a duplicate rule in the two
files worse than useless — both copies sit in context, and editing one does not
touch the other, so they drift silently. Nothing trips when they do.

What is checked here:

  - no rule is stated in two of the instruction files;
  - a set of rules removed from `CLAUDE.md` are still reachable somewhere, by a
    mechanism that does not cost context on every turn;
  - every cross-reference between the files resolves;
  - `CLAUDE.md` stays inside the size the docs recommend.

The last one is a ratchet, not a style opinion: 200 lines is the documented
target per instruction file, and the file was 290 before this partition.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
AGENTS_MD = ROOT / "AGENTS.md"
NAMING_SKILL = ROOT / ".claude" / "skills" / "naming" / "SKILL.md"
PROVENANCE_RULE = ROOT / ".claude" / "rules" / "declaration-provenance.md"

# Anthropic's documented target for a CLAUDE.md is under 200 lines: "Longer
# files consume more context and reduce adherence." The runtime's own warning
# threshold is 40,000 characters, which is why nothing fires today — the
# guidance is what applies, not the trigger.
MAX_LINES = 200


def _flat(path: Path) -> str:
    """Prose with whitespace collapsed.

    Asserting a literal phrase against a wrapped markdown file is brittle: the
    sentence can be correct and the test red, purely because an editor
    rewrapped the line. That is the worst way for a guard to fail — it teaches
    the next person that the rule is optional.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _paragraphs(path: Path) -> list[str]:
    return [re.sub(r"\s+", " ", p).strip()
            for p in path.read_text(encoding="utf-8").split("\n\n")]


def _lines(path: Path) -> set[str]:
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if len(ln.strip()) >= 60}


class PartitionTests(unittest.TestCase):
    """The two instruction files are partitioned by subject, not overlapping."""

    # Paths named to describe where architecture GOES, not what is there.
    #
    # The instruction files rank `architecture/contracts/` above everything
    # else and tell ac-designer which directories it edits. Both statements
    # stay true while the directories are absent, because neither claims a
    # file lives at that path today. They are listed rather than worked around
    # so that adding a pointer of any other kind is still a failure.
    #
    # Creating the directories to satisfy the check would be the wrong repair.
    # An empty tracked directory cannot exist in git, so the only way to make
    # the path resolve is a placeholder file — and that makes the absence
    # resolve, which is precisely the wrong signal: a reader finding
    # `architecture/contracts/` present concludes the architecture was
    # considered and produced this, rather than that nothing is declared yet.
    NOT_YET_DECLARED = {"architecture/contracts/", "architecture/modules/"}

    def test_no_long_line_appears_in_both_instruction_files(self) -> None:
        shared = _lines(CLAUDE_MD) & _lines(AGENTS_MD)
        self.assertEqual(
            shared, set(),
            "these lines are in both CLAUDE.md and AGENTS.md. Both are loaded "
            f"into every session, so one of them will drift: {sorted(shared)[:3]}",
        )

    def test_each_rule_lives_in_exactly_one_place(self) -> None:
        """The specific rules that used to be in both, or in neither.

        `owner` is the only file allowed to contain the marker. A marker in
        the other file is a duplicate; a marker in neither is a rule that was
        dropped rather than moved.
        """
        cases = [
            ("UNKNOWN` is a legal answer", "AGENTS.md"),
            ("fixture is a test input", "AGENTS.md"),
            ("Names are not evidence", "AGENTS.md"),
            ("Absence of evidence is not a pass", "AGENTS.md"),
            ("Record the coordinates", "AGENTS.md"),
            ("Source hierarchy", "AGENTS.md"),
            ("`bin/python` is a two-line shim", "AGENTS.md"),
            ("Authority order", "AGENTS.md"),
            ("$ARCHCTL readable", "CLAUDE.md"),
            ("$ARCHCTL validate", "CLAUDE.md"),
            ("Chinese writing", "CLAUDE.md"),
            ("对……进行 X", "CLAUDE.md"),
        ]
        texts = {"CLAUDE.md": _flat(CLAUDE_MD), "AGENTS.md": _flat(AGENTS_MD)}
        for marker, owner in cases:
            with self.subTest(rule=marker):
                self.assertIn(marker, texts[owner], f"{owner} lost {marker!r}")
                other = [n for n in texts if n != owner][0]
                self.assertNotIn(
                    marker, texts[other],
                    f"{marker!r} is stated in both {owner} and {other}",
                )

    def test_a_cross_reference_is_a_pointer_and_not_a_restatement(self) -> None:
        """CLAUDE.md names a few of AGENTS.md's rules so an agent knows what it
        is looking at. Naming is allowed; restating is not.

        The difference is checkable: a mention in the non-owning file has to
        sit in a paragraph that also points at the owning file, which is what
        makes it a pointer. This is one-directional on purpose — a mention
        inside AGENTS.md is in the owner and needs no pointer, and asserting
        otherwise would have flagged AGENTS.md's own rule text as a duplicate
        of itself.

        Without this, "the link alone is not enough" and "do not duplicate the
        rule" are in direct conflict, and the files drift toward whichever one
        the last editor happened to prefer.
        """
        for marker in ("UNKNOWN", "CONTRACT_INSUFFICIENT", "BOUNDARY_VIOLATION"):
            for para in _paragraphs(CLAUDE_MD):
                if marker in para:
                    with self.subTest(marker=marker):
                        self.assertIn(
                            "AGENTS.md", para,
                            f"CLAUDE.md mentions {marker} in a paragraph that "
                            f"does not point at AGENTS.md — that is a second "
                            f"copy of the rule, not a reference to it",
                        )

    def test_the_always_loaded_pair_stays_small(self) -> None:
        """A ratchet, not a quota.

        `CLAUDE.md` is held to the documented 200-line target, which it now
        clears with room to spare (it was 290). `AGENTS.md` is held to the size
        it actually is after the partition, so it can only shrink from here.

        The second bar is deliberately looser than the first, and that is a
        judgement rather than an oversight: AGENTS.md is the constraint core,
        and hitting 200 there would mean deleting isolation and external-facts
        rules to hit a number. Its five sections are the content most likely to
        be silently missed and least recoverable when missed. If it should
        shrink, that should be a decision about which rule moves, not a side
        effect of a line budget — and the decision is recorded when it happens.
        """
        for path, limit in ((CLAUDE_MD, 200), (AGENTS_MD, 295)):
            with self.subTest(file=path.name):
                n = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(
                    n, limit,
                    f"{path.name} is {n} lines, over its {limit}-line ratchet. Move a "
                    f"rule to a skill or a .claude/rules/ file rather than "
                    f"growing this one.",
                )

    def test_every_agents_md_section_reference_resolves(self) -> None:
        """CLAUDE.md points at AGENTS.md sections. A renumbering that misses
        this leaves an agent looking for a rule that is not there."""
        headings = set(re.findall(r"^## (\d+)\.", AGENTS_MD.read_text(encoding="utf-8"), re.M))
        refs = set(re.findall(r"AGENTS\.md §(\d+)", CLAUDE_MD.read_text(encoding="utf-8")))
        for ref in sorted(refs):
            with self.subTest(section=ref):
                self.assertIn(ref, headings, f"CLAUDE.md cites AGENTS.md §{ref}, "
                                             f"which has no heading")

    def test_referenced_paths_exist(self) -> None:
        """Both files name concrete paths. A moved file leaves a pointer that
        resolves to nothing, and a pointer to nothing reads as a fact."""
        for path in (CLAUDE_MD, AGENTS_MD):
            for ref in sorted(set(re.findall(r"`((?:architecture|framework|tools|"
                                             r"docs|modules|\.claude)/[A-Za-z0-9_./*-]+)`",
                                             path.read_text(encoding="utf-8")))):
                if "*" in ref or ref in self.NOT_YET_DECLARED:
                    continue
                with self.subTest(file=path.name, ref=ref):
                    self.assertTrue((ROOT / ref).exists(), f"{path.name} names {ref}")


class ExtractedGuidanceTests(unittest.TestCase):
    """What left CLAUDE.md is still reachable, and by a cheaper mechanism."""

    def test_the_naming_rules_are_a_skill_with_a_load_bearing_description(self) -> None:
        self.assertTrue(NAMING_SKILL.is_file(), f"{NAMING_SKILL} is missing")
        text = NAMING_SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"), "the skill needs YAML frontmatter")
        front = text.split("---", 2)[1]
        # Only name + description load at session start; the body does not. If
        # the description goes, nothing triggers it and the rules are gone.
        self.assertRegex(front, r"(?m)^description:\s*\S")
        self.assertIn("Make it searchable", text)
        self.assertNotIn("Make it searchable", _flat(CLAUDE_MD))

    def test_the_provenance_walk_is_gated_on_the_paths_it_applies_to(self) -> None:
        self.assertTrue(PROVENANCE_RULE.is_file(), f"{PROVENANCE_RULE} is missing")
        text = PROVENANCE_RULE.read_text(encoding="utf-8")
        front = text.split("---", 2)[1]
        self.assertRegex(front, r"(?ms)^paths:\s*\n\s*-\s*[\"']?architecture/")
        self.assertIn("Existence is a hypothesis", _flat(PROVENANCE_RULE))

    def test_the_method_document_is_still_reachable_from_both_files(self) -> None:
        for path in (CLAUDE_MD, PROVENANCE_RULE):
            with self.subTest(file=path.name):
                self.assertIn("DECLARATION-PROVENANCE.md", _flat(path))
        self.assertTrue((ROOT / "docs" / "design" / "DECLARATION-PROVENANCE.md").is_file())


class RuntimeClaimTests(unittest.TestCase):
    """CLAUDE.md used to assert how subagents inherit instruction files. It was
    wrong, and nothing tripped — the runtime does not read this file to check
    itself. The assertion is now tested instead of merely stated."""

    def test_it_does_not_claim_subagents_inherit_nothing(self) -> None:
        text = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertNotIn("and nothing else", _flat(CLAUDE_MD))
        self.assertNotIn("`AGENTS.md` is **not** auto-injected", _flat(CLAUDE_MD))

    def test_it_states_what_a_subagent_actually_receives(self) -> None:
        """Verified against the 2.1.284 binary: the Agent tool injects the
        loaded CLAUDE.md hierarchy and tells the caller not to re-send it."""
        text = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertRegex(_flat(CLAUDE_MD), r"(?i)spawned agent already receives")
        self.assertRegex(_flat(CLAUDE_MD), r"(?i)do \*\*not\*\* paste their rules")

    def test_independence_is_attributed_to_the_conversation_not_the_files(self) -> None:
        """The reason to spawn ac-designer is not inheriting the dispatcher's
        context. CLAUDE.md is static, so omitting it would buy no independence
        from the dispatcher while stripping the role of the boundary rules it
        most needs — which is why `omitClaudeMd` is deliberately not set."""
        ac = (ROOT / ".claude" / "agents" / "ac-designer.md").read_text(encoding="utf-8")
        for role in ROOT.glob(".claude/agents/*.md"):
            with self.subTest(role=role.name):
                self.assertNotIn("omitClaudeMd", role.read_text(encoding="utf-8"))
        self.assertIn("Independence comes from not inheriting the conversation",
                      _flat(CLAUDE_MD))
        self.assertTrue(ac)  # the role file still exists and is non-empty


if __name__ == "__main__":
    unittest.main()
