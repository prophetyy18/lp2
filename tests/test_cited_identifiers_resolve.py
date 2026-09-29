"""Do the identifiers our contracts cite actually resolve to something here?

The contracts cite task numbers (`T0xx`), architecture decision records
(`ADR-xxx`) and requirement ids (`G-*-xx`) in their capability descriptions:

    "Historical ingestion: plan ranges, route by capability, ... (T032)"
    "The isolated signer process (G-S-G-01)"
    "Integer arithmetic only on the protocol path (ADR-004)"

A citation looks like support. It is not. Each of those three resolves to
nothing in this repository: there is no task list, no ADR file, no
requirements document. So 21 of 57 capabilities justify themselves partly with
an index into a document that is not here — one spanning T020..T113 with 58
slots absent, against a repository of 12 contracts with nothing implemented.

That is the same shape as the other two retired foreign vocabularies
(`market-data`'s OHLCV, and `Bar` inheriting a shape from a capability with
zero consumers), and it survives review for the same reason: a citation is not
an edit. See `docs/design/DECLARATION-PROVENANCE.md` step 4.

The list below is a ratchet. It may shrink; it may not grow. If the task
tracker is ever added to this repository, delete the entry and the test holds
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
    # 35 identifiers, none of which resolve against anything in this
    # repository. Recorded so that ADDING one fails this test, and so that
    # removing one is a visible, deliberate edit.
    UNRESOLVED = {
        "T020", "T024", "T031", "T032", "T033", "T037", "T040", "T041",
        "T042", "T049", "T050", "T051", "T052", "T053", "T060", "T061",
        "T068", "T070", "T071", "T072", "T073", "T087", "T088", "T090",
        "T094", "T097", "T100", "T101", "T102", "T103", "T104", "T109",
        "T110", "T111", "T112", "T113",
        "ADR-004", "ADR-006", "ADR-009", "ADR-016",
        "G-S-G-01", "G-SIGNER-01",
    }

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
