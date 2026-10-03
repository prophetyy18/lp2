"""Do the identifiers our declarations cite actually resolve to something here?

The twelve `robinhood-*` contracts cited task numbers (`T0xx`), architecture
decision records (`ADR-xxx`) and requirement ids (`G-*-xx`) in their capability
descriptions:

    "Historical ingestion: plan ranges, route by capability, ... (T032)"
    "The isolated signer process (G-S-G-01)"
    "Integer arithmetic only on the protocol path (ADR-004)"

A citation looks like support. It was not. Each of those resolved to nothing
in this repository: there is no task list, no ADR file, no requirements
document. So 21 of 57 capabilities justified themselves partly with an index
into a document that is not here — one spanning T020..T113 with 58 slots
absent, against a repository of 12 contracts with nothing implemented.

That was the same shape as the other retired foreign vocabularies
(`market-data`'s OHLCV, and `Bar` inheriting a shape from a capability with
zero consumers), and it survived review for the same reason: a citation is not
an edit. See `docs/design/DECLARATION-PROVENANCE.md` step 4.

Those twelve modules were withdrawn on 2026-10-03, and with them every
citation. What is left is a ratchet with an empty chamber, and that is the
state worth holding: the question this file exists to ask is now answerable
for the first time, and the answer is that nothing in this repository cites an
identifier that resolves to nothing.

The list may shrink; it may not grow. If a task tracker is ever added to this
repository, the citation it backs stops being unresolvable, and the test holds
without weakening.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "architecture"

# T0xx = a task in some tracker; ADR-xxx = a decision record; G-*-xx = a
# requirement. All three are cross-references, and all three are expected to
# point at a document in THIS repository.
CITED = re.compile(r"\b(?:T\d{3}|ADR-\d{3}|G-[A-Z]+(?:-[A-Z]+)*-\d{2})\b")


def cited_identifiers() -> dict[str, set[str]]:
    """Every cited identifier -> the files that cite it."""
    found: dict[str, set[str]] = {}
    for path in sorted(ARCH.rglob("*.yaml")):
        for match in CITED.findall(path.read_text(encoding="utf-8")):
            found.setdefault(match, set()).add(path.relative_to(ROOT).as_posix())
    return found


class CitedIdentifiersTests(unittest.TestCase):
    # EMPTY, and that is the answer, not an absence of one.
    #
    # It was 41. Every one of them is gone because the declarations that cited
    # them are: the twelve `robinhood-*` contracts and modules were withdrawn
    # on 2026-10-03 as a design mapped in from another repository, and a
    # citation cannot outlive its citing sentence. `T020` went earlier, on
    # 2026-10-02, the same way -- a rewrite that dropped the sentence dropped
    # the citation with it. Both times `test_the_ratchet_list_is_not_stale`
    # is what surfaced the removal, by reporting the entry as listed but
    # uncited, and dropping it is the deliberate edit that test asks for.
    #
    # So the question this file exists to ask -- does anything in this
    # repository still cite an identifier that resolves to nothing? -- now has
    # an answer for the first time, and the answer is no. A ratchet with an
    # empty chamber is the strongest state it can be in: the first citation
    # added from here on fails `test_no_new_unresolvable_identifier_is_cited`,
    # and there is nothing left to forgive.
    UNRESOLVED: set[str] = set()

    def test_no_new_unresolvable_identifier_is_cited(self) -> None:
        new = set(cited_identifiers()) - self.UNRESOLVED
        self.assertEqual(
            new, set(),
            f"newly cited, and nothing in this repository defines it: {sorted(new)}. "
            f"Either the document it points at belongs in this repo, or the "
            f"citation is borrowed from somewhere else.",
        )

    def test_the_ratchet_list_is_not_stale(self) -> None:
        """A list that keeps entries for identifiers nobody cites any more is
        a list nobody reads. It must track reality in both directions.
        """
        gone = self.UNRESOLVED - set(cited_identifiers())
        self.assertEqual(
            gone, set(),
            f"these are still listed as unresolved but nothing cites them "
            f"any more: {sorted(gone)} -- drop them from UNRESOLVED",
        )

    def test_nothing_in_this_repository_defines_them(self) -> None:
        """The premise, stated as a test. If someone adds the task list or the
        ADRs, this fails and forces the ratchet to be re-thought rather than
        silently left in place.
        """
        for pattern, what in ((r"\bT\d{3}\b", "task list"),
                              (r"\bADR-\d{3}\b", "ADR file"),
                              (r"\bG-[A-Z]+(?:-[A-Z]+)*-\d{2}\b", "requirements doc")):
            with self.subTest(looking_for=what):
                hits = [
                    p.relative_to(ROOT).as_posix()
                    for p in ROOT.rglob("*")
                    if p.is_file()
                    and ".git" not in p.parts
                    and p.suffix in {".md", ".yaml", ".yml"}
                    and "architecture/" not in p.relative_to(ROOT).as_posix()
                    and re.search(rf"^#+\s*{pattern}", p.read_text(errors="ignore"), re.M)
                ]
                self.assertEqual(
                    hits, [],
                    f"a {what} now exists at {hits} -- the cited identifiers may "
                    f"resolve, re-check UNRESOLVED",
                )


if __name__ == "__main__":
    unittest.main()
