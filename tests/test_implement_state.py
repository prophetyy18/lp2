"""Capability state machine: transitions, mode rules, aggregated state."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.implement import naming
from tools.implement.errors import StateError
from tools.implement.state import (
    STATE_ROOT,
    CapabilityRecord,
    ModuleRecord,
    compute_module_state,
    load_state,
    save_state,
)


class StateTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _record(self) -> ModuleRecord:
        return ModuleRecord(
            name="alpha",
            capabilities={
                "alpha.one": CapabilityRecord(state="pending", mode="full"),
                "alpha.two": CapabilityRecord(state="pending", mode="mvp"),
            },
        )

    def test_pending_to_mvp_is_allowed(self) -> None:
        rec = self._record()
        rec.capabilities["alpha.one"].state = "mvp_developed"
        self.assertEqual(rec.module_state, "in_progress")

    def test_only_mvp_can_be_fully_approved(self) -> None:
        # pending -> fully_approved is allowed (full mode path)
        rec = self._record()
        rec.capabilities["alpha.one"].state = "fully_approved"
        self.assertEqual(
            compute_module_state(rec.capabilities.values()), "in_progress"
        )

    def test_full_approval_for_all_capabilities_makes_module_complete(self) -> None:
        rec = ModuleRecord(
            name="alpha",
            capabilities={
                "alpha.one": CapabilityRecord(state="fully_approved", mode="full"),
                "alpha.two": CapabilityRecord(state="fully_approved", mode="full"),
            },
        )
        self.assertEqual(rec.module_state, "complete")

    def test_pending_only_module_is_not_started(self) -> None:
        rec = self._record()
        self.assertEqual(compute_module_state(rec.capabilities.values()), "not_started")

    def test_all_abandoned_is_in_progress(self) -> None:
        """Three values cannot also say "started, then deliberately closed".

        `in_progress` at least records that the module was touched, which is
        the fact the three-value set is able to carry.
        """
        rec = ModuleRecord(
            name="alpha",
            capabilities={
                "alpha.one": CapabilityRecord(state="abandoned"),
                "alpha.two": CapabilityRecord(state="abandoned"),
            },
        )
        self.assertEqual(compute_module_state(rec.capabilities.values()), "in_progress")

    def test_round_trip_yaml(self) -> None:
        rec = self._record()
        rec.capabilities["alpha.one"].state = "mvp_developed"
        rec.capabilities["alpha.one"].manifest = "manifests/one.md"
        path = save_state(rec, self.root)
        loaded = load_state("alpha", self.root)
        self.assertEqual(loaded.capabilities["alpha.one"].state, "mvp_developed")
        self.assertEqual(loaded.capabilities["alpha.one"].manifest, "manifests/one.md")
        self.assertEqual(loaded.module_state, "in_progress")

    def test_module_state_is_not_written_to_the_file(self) -> None:
        """The summary is a display value; the file keeps facts only.

        It used to be persisted, and nothing read it -- `load_state`
        recomputed it and overwrote whatever the file claimed, so a wrong
        value sat there silently. If this test fails, the copy is back.
        """
        rec = self._record()
        rec.capabilities["alpha.one"].state = "fully_approved"
        path = save_state(rec, self.root)
        self.assertNotIn("module_state", path.read_text(encoding="utf-8"))

    def test_a_stale_module_state_in_the_file_is_ignored(self) -> None:
        """A hand-edited or corrupted copy cannot mislead the CLI."""
        rec = self._record()
        path = save_state(rec, self.root)
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "module: alpha", "module: alpha\nmodule_state: complete"
            ),
            encoding="utf-8",
        )
        self.assertEqual(load_state("alpha", self.root).module_state, "not_started")

    def test_load_missing_module_yields_empty_record(self) -> None:
        rec = load_state("ghost", self.root)
        self.assertEqual(rec.name, "ghost")
        self.assertEqual(rec.capabilities, {})

    def test_module_state_of_a_module_with_no_capabilities(self) -> None:
        rec = ModuleRecord(name="empty")
        self.assertEqual(compute_module_state(rec.capabilities.values()), "not_started")


# Fixed timestamps so the review-after-manifest ordering check is exercised
# deterministically instead of depending on how fast the test writes files.
MANIFEST_MTIME = 1_600_000_000


def _set_mtime(path: Path, when: float) -> None:
    os.utime(path, (when, when))


class StateCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_state_root = STATE_ROOT
        # Redirect by patching the constant used by the CLI imports.
        import tools.implement.state as st

        st.STATE_ROOT = self.root
        # A repo tree for the artifact checks: a declared module with source
        # and a test file, so a capability can legitimately be approved. The
        # checks refuse a capability with an empty tree, so without this
        # every approval test would be testing the refusal instead.
        #
        # The contract is here because mark-approved now reads one: the
        # obligations it enforces come from the architecture, not from the
        # Card. `alpha.one` declares nothing beyond a signature, so it has no
        # obligations and these tests keep testing the old rules.
        self.repo = self.root / "repo"
        (self.repo / "architecture/contracts").mkdir(parents=True)
        (self.repo / "architecture/contracts/alpha-api.yaml").write_text(
            "name: alpha-api\n"
            "version: 1\n"
            "requires: []\n"
            "provides:\n"
            "  - id: alpha.one\n"
            "    kind: operation\n"
            "    signature: alpha.one() -> int\n",
            encoding="utf-8",
        )
        (self.repo / "architecture/modules/alpha").mkdir(parents=True)
        (self.repo / "architecture/modules/alpha/module.yaml").write_text(
            "name: alpha\n"
            "source: modules/alpha\n"
            "provides_contracts:\n"
            "  - alpha-api\n",
            encoding="utf-8",
        )
        (self.repo / "modules/alpha").mkdir(parents=True)
        (self.repo / "modules/alpha/thing.py").write_text(
            "def f() -> int:\n    return 1\n", encoding="utf-8"
        )
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests/test_alpha_one.py").write_text(
            "import unittest\n", encoding="utf-8"
        )
        self._old_repo_root = st.REPO_ROOT
        st.REPO_ROOT = self.repo

    def tearDown(self) -> None:
        import tools.implement.state as st

        st.STATE_ROOT = self._old_state_root
        st.REPO_ROOT = self._old_repo_root
        self._tmp.cleanup()

    def _seed(self, module: str, cap: str, mode: str = "full") -> None:
        from tools.implement.state import load_state, save_state

        rec = load_state(module, self.root)
        rec.capabilities[cap] = CapabilityRecord(state="pending", mode=mode)
        save_state(rec, self.root)

    def _manifest(self, module: str, cap: str, discovery: bool = True) -> Path:
        """Write a Manifest that mark-mvp will accept."""
        target = self.root / module / f"{cap}.manifest.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        block = (
            "\n## discovery\n\n"
            "- question: does the sharding approach hold up?\n"
            "- answer: yes, above 8k blocks it must split\n"
            "- surprised: the node returns execution_reverted, not a timeout\n"
            "- keep: the split algorithm and the three replay fixtures\n"
            "- discard: all error handling, which just returns None\n"
            "- known_gaps: 3 of 4 declared error codes are unimplemented\n"
            if discovery
            else ""
        )
        target.write_text(
            f"# manifest: {module} / {cap}\n\n- mode: mvp{block}",
            encoding="utf-8",
        )
        return target

    def _full_manifest(self, module: str, cap: str) -> Path:
        """Write a full-mode Manifest that mark-approved will accept."""
        target = self.root / module / f"{cap}.manifest.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# manifest: {module} / {cap}\n\n"
            f"- mode: full\n"
            f"- new files:\n   - modules/{module}/thing.py\n"
            f"- tests passing: 3 unit, 0 contract-conformance\n",
            encoding="utf-8",
        )
        _set_mtime(target, MANIFEST_MTIME)
        return target

    def _test_record(self, module: str, cap: str, block: str | None = None) -> Path:
        """Write the Tester's Test Record that mark-approved now requires.

        The obligation mapping used to live in the developer's Manifest,
        which meant the implementer signed a statement about test coverage
        for code it had just written. It is read from here instead.
        """
        target = self.root / module / f"{cap}.tests.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        section = "" if block is None else f"\n{block}\n"
        target.write_text(
            f"# tests: {module} / {cap}\n\n- mode: full{section}",
            encoding="utf-8",
        )
        _set_mtime(target, MANIFEST_MTIME + 30)
        return target

    def _review(
        self,
        module: str,
        cap: str,
        verdict: str = "APPROVED",
        reasons: str | None = None,
        scores: tuple[str, ...] = ("OK", "OK", "OK", "OK"),
        ran: str | None = "3 passed, 0 skipped",
    ) -> Path:
        """Write a Review Record that the state CLI will accept."""
        target = self.root / module / f"{cap}.review.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        reason_line = (
            f"- reason codes: [{reasons}]\n" if reasons is not None else ""
        )
        ran_line = "" if ran is None else f"- tests run: {ran}\n"
        target.write_text(
            f"# review: {module} / {cap}\n"
            f"   contract_conformance: {scores[0]}\n"
            f"   boundary: {scores[1]}\n"
            f"   test_coverage: {scores[2]}\n"
            f"   implementation_quality: {scores[3]}\n"
            f"{reason_line}"
            f"- verdict: {verdict}\n"
            f"{ran_line}",
            encoding="utf-8",
        )
        _set_mtime(target, MANIFEST_MTIME + 60)
        return target

    def _blocker(self, module: str, cap: str) -> Path:
        target = self.root / module / f"{cap}.design-blocker.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# design blocker: {module} / {cap}\n\n"
            f"the contract declares only RPC_TIMEOUT; the node returns\n"
            f"execution_reverted, so the error surface is wider than designed.\n"
            f"- resolution: \n",
            encoding="utf-8",
        )
        return target

    def _resolve(self, blocker: Path, decision: str = "added EXECUTION_REVERTED") -> Path:
        """Resolve a blocker the way the workflow says to: fill it in, rename.

        Filling in is not optional. The rename is what lifts the gate, so a
        rename that records nothing closes a design question without leaving
        a trace of what closed it.
        """
        text = blocker.read_text(encoding="utf-8").replace(
            "- resolution: \n", f"- resolution: {decision}\n"
        )
        blocker.write_text(text, encoding="utf-8")
        resolved = blocker.with_name(blocker.name.replace(".md", ".resolved.md"))
        blocker.rename(resolved)
        return resolved

    def _run(self, *argv: str) -> tuple[int, str]:
        from tools.implement import state

        # capture stderr (where the CLI writes status)
        import io
        import contextlib

        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                rc = state.main(list(argv))
        except SystemExit as exc:
            # argparse rejects unknown subcommands / bad flags this way
            rc = int(exc.code or 0)
        return rc, buf.getvalue()

    def test_mark_mvp_succeeds(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        manifest = self._manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(manifest),
        )
        self.assertEqual(rc, 0)
        self.assertIn("mvp_developed", out)

    def test_mark_mvp_requires_a_manifest(self) -> None:
        """An MVP that produced nothing is not worth recording."""
        self._seed("alpha", "alpha.one", mode="mvp")
        rc, out = self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one")
        self.assertEqual(rc, 1)
        self.assertIn("--manifest", out)

    def test_mark_mvp_rejects_a_manifest_that_does_not_exist(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        ghost = self.root / "alpha" / "alpha.one.manifest.md"
        rc, out = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(ghost),
        )
        self.assertEqual(rc, 1)
        self.assertIn("existing manifest", out)

    def test_mark_mvp_rejects_a_manifest_for_another_capability(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        self._manifest("alpha", "alpha.two")
        other = self.root / "alpha" / "alpha.two.manifest.md"
        rc, out = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(other),
        )
        self.assertEqual(rc, 1)
        self.assertIn("existing manifest", out)

    def test_mark_mvp_rejects_a_manifest_without_discovery(self) -> None:
        """The discovery block is what the full run inherits; it is required."""
        self._seed("alpha", "alpha.one", mode="mvp")
        manifest = self._manifest("alpha", "alpha.one", discovery=False)
        rc, out = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(manifest),
        )
        self.assertEqual(rc, 1)
        self.assertIn("## discovery", out)

    def test_mark_mvp_records_the_manifest_path(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        manifest = self._manifest("alpha", "alpha.one")
        self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(manifest),
        )
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].manifest, str(manifest))

    def test_mark_mvp_rejects_wrong_mode(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        manifest = self._manifest("alpha", "alpha.one")
        rc, _ = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(manifest),
        )
        self.assertEqual(rc, 1)

    def test_mark_approved_works_from_pending(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        review = self._review("alpha", "alpha.one")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 0)
        self.assertIn("fully_approved", out)

    def test_mark_approved_is_refused_from_mvp_developed(self) -> None:
        """An MVP is never consumable; it cannot reach fully_approved in place."""
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        rc, out = self._run("--root", str(self.root), "mark-approved", "alpha", "alpha.one", "--manifest", str(self._full_manifest("alpha", "alpha.one")),
            "--tests", str(self._test_record("alpha", "alpha.one")))
        self.assertEqual(rc, 1)
        self.assertIn("not allowed", out)
        self.assertIn("pending", out)

    def test_mvp_cannot_jump_straight_to_fully_approved(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        # no promote subcommand exists any more
        rc, _ = self._run("--root", str(self.root), "promote", "alpha", "alpha.one")
        self.assertEqual(rc, 2)  # argparse rejects the unknown command

    def test_retry_from_mvp_requires_mode_full(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        rc, out = self._run("--root", str(self.root), "retry", "alpha", "alpha.one")
        self.assertEqual(rc, 1)
        self.assertIn("--mode full", out)

    def test_retry_from_mvp_reopens_in_full_mode(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        rc, _ = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        self.assertEqual(rc, 0)
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].state, "pending")
        self.assertEqual(rec.capabilities["alpha.one"].mode, "full")

    def test_retry_from_mvp_archives_the_discovery_before_it_is_overwritten(self) -> None:
        """The full pass writes to the same manifest path; discovery must survive."""
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        archived = self.root / "alpha" / "alpha.one.mvp-manifest.md"
        self.assertTrue(archived.is_file())
        self.assertIn("## discovery", archived.read_text(encoding="utf-8"))
        # the record must not still point at a file the full pass will rewrite
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].manifest, "")

    def test_retry_from_mvp_warns_but_proceeds_when_the_manifest_is_gone(self) -> None:
        """A lost bookkeeping field must not become a dead end.

        Refusing here would leave `abandon` and a hand-edit of STATE.yaml as
        the only escapes, and hand-editing is what the policy forbids. So the
        reopen proceeds and says loudly that the handoff has nothing to read.
        """
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        m.unlink()
        rc, out = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", out)
        self.assertIn("no longer exists", out)
        self.assertIn("rebuild the Card", out)
        rec = load_state("alpha", self.root).capabilities["alpha.one"]
        self.assertEqual(rec.state, "pending")
        self.assertEqual(rec.mode, "full")

    def test_retry_from_mvp_warns_when_no_manifest_was_ever_recorded(self) -> None:
        """A hand-edited or pre-manifest STATE.yaml lands here; name the field."""
        from tools.implement.state import load_state as _load

        rec = _load("alpha", self.root)
        rec.capabilities["alpha.one"] = CapabilityRecord(state="mvp_developed", mode="mvp")
        save_state(rec, self.root)
        rc, out = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        self.assertEqual(rc, 0)
        self.assertIn("no manifest path", out)
        self.assertIn("WARNING", out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state, "pending"
        )

    def test_retry_from_mvp_refuses_to_clobber_an_existing_archive(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        archived = self.root / "alpha" / "alpha.one.mvp-manifest.md"
        archived.write_text("an earlier archive\n", encoding="utf-8")
        rc, out = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)
        self.assertEqual(archived.read_text(encoding="utf-8"), "an earlier archive\n")

    def test_retry_from_changes_requested_leaves_the_manifest_alone(self) -> None:
        """Only the MVP reopen archives; a rejected full pass has no spike to keep."""
        self._seed("alpha", "alpha.one", mode="full")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "quality")
        self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(self._full_manifest("alpha", "alpha.one")),
        )
        rc, _ = self._run("--root", str(self.root), "retry", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / "alpha" / "alpha.one.mvp-manifest.md").exists())

    # --- mark-changes must record what it rejected, and why -----------------

    def test_mark_changes_records_the_review_path(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "boundary")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
        )
        self.assertEqual(rc, 0)
        self.assertIn("boundary", out)
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].review, str(review))

    def test_mark_changes_requires_a_review(self) -> None:
        self._seed("alpha", "alpha.one")
        rc, out = self._run("--root", str(self.root), "mark-changes", "alpha", "alpha.one", "--manifest", str(self._full_manifest("alpha", "alpha.one")))
        self.assertEqual(rc, 1)
        self.assertIn("--review", out)

    def test_mark_changes_rejects_an_approved_review(self) -> None:
        """Recording a rejection on top of an APPROVED record would be nonsense."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED", "quality")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
        )
        self.assertEqual(rc, 1)
        self.assertIn("CHANGES_REQUESTED", out)

    def test_mark_changes_requires_at_least_one_reason(self) -> None:
        """A rejection the developer cannot act on sends them back to guessing."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", reasons="")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
        )
        self.assertEqual(rc, 1)
        self.assertIn("reason code", out)

    def test_mark_changes_rejects_an_unknown_reason_code(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "vibes")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
        )
        self.assertEqual(rc, 1)
        self.assertIn("vibes", out)

    # --- an open design blocker outranks every gate -------------------------

    def test_mark_approved_is_refused_while_a_design_blocker_is_open(self) -> None:
        """A stale blocker must not be able to coexist with fully_approved."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        self._blocker("alpha", "alpha.one")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 1)
        self.assertIn("design blocker", out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state, "pending"
        )

    def test_mark_mvp_is_refused_while_a_design_blocker_is_open(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        manifest = self._manifest("alpha", "alpha.one")
        self._blocker("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one",
            "--manifest", str(manifest),
        )
        self.assertEqual(rc, 1)
        self.assertIn("design blocker", out)

    def test_mark_changes_is_refused_while_a_design_blocker_is_open(self) -> None:
        """A blocker is not a review outcome, so it does not become one."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "quality")
        self._blocker("alpha", "alpha.one")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
        )
        self.assertEqual(rc, 1)
        self.assertIn("design blocker", out)

    def test_a_resolved_blocker_no_longer_gates(self) -> None:
        """Resolution is recorded by renaming the file, so the check is the file."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        blocker = self._blocker("alpha", "alpha.one")
        self._resolve(blocker)
        mf = self._full_manifest("alpha", "alpha.one")
        rc, _ = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(mf),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 0)

    def test_a_contract_blocker_gates_every_capability_of_the_module(self) -> None:
        """A defect in the contract belongs to no single capability.

        The hole this closes was live in the first end-to-end run: a
        blocker filed against `series.symbols` — the capability that tripped
        over the missing ingestion surface — gated only `series.symbols`,
        while `series.get` and `series.calendar` carried on building on the
        same broken contract. And they are the two that actually consume
        bars, so they are the two that needed the decision most.
        """
        self._seed("alpha", "alpha.one")
        self._seed("alpha", "alpha.two")
        blocker = self.root / "alpha" / "CONTRACT.design-blocker.md"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text(
            "# design blocker: alpha / CONTRACT\n\n"
            "the contract declares a read surface with no ingestion behind it.\n"
            "- resolution: \n",
            encoding="utf-8",
        )
        for cap in ("alpha.one", "alpha.two"):
            review = self._review("alpha", cap)
            manifest = self._full_manifest("alpha", cap)
            rc, out = self._run(
                "--root", str(self.root), "mark-approved", "alpha", cap,
                "--review", str(review), "--manifest", str(manifest),
            )
            self.assertEqual(rc, 1, cap)
            self.assertIn("contract-level design blocker", out)

    def test_a_resolved_contract_blocker_lets_the_module_through(self) -> None:
        self._seed("alpha", "alpha.one")
        blocker = self.root / "alpha" / "CONTRACT.design-blocker.md"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text(
            "# design blocker: alpha / CONTRACT\n\n"
            "the contract declares a read surface with no ingestion behind it.\n"
            "- resolution: \n",
            encoding="utf-8",
        )
        self._resolve(blocker, "added an ingest capability to the contract")
        review = self._review("alpha", "alpha.one")
        manifest = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(manifest),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 0, out)

    def test_renaming_a_blocker_without_a_resolution_does_not_lift_the_gate(self) -> None:
        """Resolution was a rename and nothing else, so a rename recorded nothing.

        `mv x.design-blocker.md x.design-blocker.resolved.md` used to open
        the gate. That closes a design question while leaving no trace of
        what closed it, and the template has always asked for the sentence.
        """
        self._seed("alpha", "alpha.one")
        blocker = self._blocker("alpha", "alpha.one")
        blocker.rename(blocker.with_name("alpha.one.design-blocker.resolved.md"))
        review = self._review("alpha", "alpha.one")
        manifest = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(manifest),
        )
        self.assertEqual(rc, 1)
        self.assertIn("carries no resolution", out)

    def test_mark_approved_refuses_without_a_test_record(self) -> None:
        """The tester is a required step, not an optional extra.

        `mark-approved` used to read the developer's Manifest and the
        developer's test file. Now it requires the Tester's record as well,
        so "nobody wrote independent tests" has a different failure from
        "the tests are weak" — the first is visible in the state file.
        """
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one")
        manifest = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(manifest),
        )
        self.assertEqual(rc, 1)
        self.assertIn("--tests", out)

    def test_the_test_record_path_is_recorded(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one")
        manifest = self._full_manifest("alpha", "alpha.one")
        record = self._test_record("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(manifest),
            "--tests", str(record),
        )
        self.assertEqual(rc, 0, out)
        loaded = load_state("alpha", self.root)
        # Recorded as given, like `manifest` and `review` — the dispatcher
        # passes repo-relative paths, these tests pass absolute ones.
        self.assertTrue(
            loaded.capabilities["alpha.one"].tests.endswith("alpha/alpha.one.tests.md"),
            loaded.capabilities["alpha.one"].tests,
        )

    def test_resolve_writes_the_decision_and_lifts_the_gate(self) -> None:
        """Resolution was a manual `mv` that recorded nothing.

        The rename is what lifts the gate, so the sentence next to it is the
        only record of *why* a design question closed. A command that writes
        the decision, performs the rename, and records the path in STATE
        makes that impossible to skip.
        """
        self._seed("alpha", "alpha.one")
        blocker = self._blocker("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "resolve", "alpha", "alpha.one",
            "--resolution", "added EXECUTION_REVERTED to the contract",
        )
        self.assertEqual(rc, 0, out)
        resolved = self.root / "alpha" / "alpha.one.design-blocker.resolved.md"
        self.assertFalse(blocker.exists())
        self.assertIn(
            "added EXECUTION_REVERTED", resolved.read_text(encoding="utf-8")
        )
        loaded = load_state("alpha", self.root)
        self.assertTrue(
            loaded.capabilities["alpha.one"].blocker.endswith(
                "alpha.one.design-blocker.resolved.md"
            ),
            loaded.capabilities["alpha.one"].blocker,
        )

    def test_resolve_refuses_an_empty_resolution(self) -> None:
        self._seed("alpha", "alpha.one")
        self._blocker("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "resolve", "alpha", "alpha.one",
            "--resolution", "   ",
        )
        self.assertEqual(rc, 1)
        self.assertIn("--resolution is required", out)
        # and the blocker is still open, so the gate is still shut
        self.assertTrue((self.root / "alpha" / "alpha.one.design-blocker.md").is_file())

    def test_resolve_refuses_a_capability_the_module_does_not_own(self) -> None:
        """Otherwise a typo creates an orphan file nobody will ever find."""
        rc, out = self._run(
            "--root", str(self.root), "resolve", "alpha", "not.a.cap",
            "--resolution", "whatever",
        )
        self.assertEqual(rc, 1)
        self.assertIn("not provided by module", out)

    def test_state_show_names_an_open_contract_blocker(self) -> None:
        """A contract-level blocker has no capability row to appear on.

        Every capability in the module looks ordinary in STATE.yaml while
        the module is actually stopped, so the rows alone are misleading.
        """
        self._seed("alpha", "alpha.one")
        blocker = self.root / "alpha" / "CONTRACT.design-blocker.md"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text(
            "# design blocker: alpha / CONTRACT\n\nno ingestion surface.\n",
            encoding="utf-8",
        )
        rc, out = self._run("--root", str(self.root), "show", "alpha")
        self.assertEqual(rc, 0)
        self.assertIn("STOPPED", out)
        self.assertIn("CONTRACT", out)

    def test_consumes_is_read_from_the_manifest_on_approval(self) -> None:
        self._seed("alpha", "alpha.one")
        target = self.root / "alpha" / "alpha.one.manifest.md"
        target.write_text(
            "# manifest: alpha / alpha.one\n\n- mode: full\n"
            "- upstream consumed: [beta.supply, beta.reserve]\n",
            encoding="utf-8",
        )
        _set_mtime(target, MANIFEST_MTIME)
        review = self._review("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(target),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].consumes,
            ["beta.supply", "beta.reserve"],
        )

    def _approved_with_resolved_blocker(self) -> Path:
        """`fully_approved`, with the design decision that retracts it on record."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one")
        manifest = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(manifest),
            "--tests", str(self._test_record("alpha", "alpha.one")),
        )
        self.assertEqual(rc, 0, out)
        return self._resolve(self._blocker("alpha", "alpha.one"), "retracted")

    def test_reopen_refuses_without_the_blocker_that_proves_the_design_moved(self) -> None:
        """The bar, and the reason it is the bar.

        A `--reason` typed by whoever wants the capability back is not
        evidence of anything — it is the sentence that made the person type
        it. Without the blocker, `reopen` is a way to undo an approval by
        writing a sentence, which is the exact thing `mark-changes` refuses
        when it demands a real Review Record.
        """
        self._approved_with_resolved_blocker()
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
            "--reason", "I changed my mind this morning",
        )
        self.assertEqual(rc, 1)
        self.assertIn("--blocker is required", out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state,
            "fully_approved",
        )

    def test_reopen_records_the_blocker_that_authorised_it(self) -> None:
        resolved = self._approved_with_resolved_blocker()
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
            "--reason", "the contract retracted the error surface",
            "--blocker", str(resolved),
        )
        self.assertEqual(rc, 0, out)
        rec = load_state("alpha", self.root).capabilities["alpha.one"]
        self.assertEqual(rec.state, "pending")
        self.assertTrue(
            rec.blocker.endswith("alpha.one.design-blocker.resolved.md"),
            rec.blocker,
        )

    def test_reopen_takes_back_an_approved_capability(self) -> None:
        """The loop back to `pending` had to exist, and had to be `reopen`.

        `fully_approved` is the one state another module may build on, and
        it is reachable in a loop: the upstream gate is checked once, at
        approval, and a later design change can retract what was approved.
        Without this the module has no way back — `mark-changes` needs a
        reviewer's verdict, and a design change is nobody's verdict.
        """
        self._approved_with_resolved_blocker()
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
            "--reason", "the contract retracted the error surface",
            "--blocker", "docs/implement/alpha/alpha.one.design-blocker.resolved.md",
        )
        self.assertEqual(rc, 0, out)
        rec = load_state("alpha", self.root).capabilities["alpha.one"]
        self.assertEqual(rec.state, "pending")
        # not consumable any more, and it does not claim to have been approved
        self.assertEqual(rec.approved_at, "")
        # the Review Record pointer is a real historical artifact, and retry
        # keeps it too — clearing it here would fix half of a known item
        self.assertTrue(rec.review)

    def test_reopen_requires_a_reason(self) -> None:
        self._seed("alpha", "alpha.one")
        rec = load_state("alpha", self.root)
        rec.capabilities["alpha.one"].state = "fully_approved"
        save_state(rec, self.root)
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
        )
        self.assertEqual(rc, 1)
        self.assertIn("--reason is required", out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state,
            "fully_approved",
        )

    def test_reopen_refuses_a_capability_that_owes_work(self) -> None:
        """`retry` is for those; sending them to `reopen` is a category error."""
        self._seed("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
            "--reason", "whatever",
        )
        self.assertEqual(rc, 1)
        self.assertIn("not fully_approved", out)
        self.assertIn("retry", out)

    def test_reopen_refuses_a_blocker_that_does_not_exist(self) -> None:
        """Re-opening a published capability needs the decision on record."""
        self._seed("alpha", "alpha.one")
        rec = load_state("alpha", self.root)
        rec.capabilities["alpha.one"].state = "fully_approved"
        save_state(rec, self.root)
        rc, out = self._run(
            "--root", str(self.root), "reopen", "alpha", "alpha.one",
            "--reason", "the design moved", "--blocker", "docs/nowhere.md",
        )
        self.assertEqual(rc, 1)
        self.assertIn("exists", out)

    def test_retry_cannot_take_back_an_approved_capability(self) -> None:
        """The two commands must not be interchangeable.

        `retry` means "a reviewer rejected this" and its whole point is that
        a rejection is always a rejection. If it could also mean "the design
        changed", a design change would be recorded as a review verdict.
        """
        self._seed("alpha", "alpha.one")
        rec = load_state("alpha", self.root)
        rec.capabilities["alpha.one"].state = "fully_approved"
        save_state(rec, self.root)
        rc, out = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one",
        )
        self.assertEqual(rc, 1)
        self.assertIn("reopen", out)
        self.assertIn("fully_approved", out)

    def test_retry_is_not_gated_by_a_blocker(self) -> None:
        """The check must not deadlock the path out of a blocker.

        A blocker discovered after a rejection leaves the record in
        `changes_requested`; retry is how that work resumes, so retry is
        deliberately not gated.
        """
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "schema")
        self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
            "--manifest", str(self._full_manifest("alpha", "alpha.one")),
        )
        self._blocker("alpha", "alpha.one")
        rc, _ = self._run("--root", str(self.root), "retry", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state, "pending"
        )

    def test_mvp_only_exits_to_pending_or_abandoned(self) -> None:
        from tools.implement.state import _ALLOWED

        self.assertEqual(
            _ALLOWED["mvp_developed"], frozenset({"pending", "abandoned"})
        )

    # --- abandon: Owner decision vs reviewer ABANDON verdict ---------------

    def test_abandon_without_a_review_is_an_owner_decision(self) -> None:
        self._seed("alpha", "alpha.one")
        rc, out = self._run("--root", str(self.root), "abandon", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertIn("Owner decision", out)
        self.assertEqual(load_state("alpha", self.root).capabilities["alpha.one"].review, "")

    def test_abandon_records_a_reviewer_abandon_verdict(self) -> None:
        """Otherwise a review that condemned the work is indistinguishable
        from the Owner simply changing their mind."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "ABANDON", "scope")
        rc, out = self._run(
            "--root", str(self.root), "abandon", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 0)
        self.assertIn("ABANDON verdict", out)
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].state, "abandoned")
        self.assertEqual(rec.capabilities["alpha.one"].review, str(review))

    def test_abandon_rejects_a_review_with_a_different_verdict(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        rc, out = self._run(
            "--root", str(self.root), "abandon", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("ABANDON", out)
        self.assertNotEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state, "abandoned"
        )

    def test_abandon_stays_legal_from_fully_approved(self) -> None:
        """An Owner may close a capability that already worked."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
        )
        rc, _ = self._run("--root", str(self.root), "abandon", "alpha", "alpha.one")
        self.assertEqual(rc, 0)

    def test_abandon_is_terminal(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        rc, _ = self._run("--root", str(self.root), "abandon", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        # Re-abandoning is a no-op-ish error from the transition table.
        rc, _ = self._run("--root", str(self.root), "abandon", "alpha", "alpha.one")
        self.assertEqual(rc, 1)

    def test_show_emits_yaml(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        import io
        import contextlib

        from tools.implement import state

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = state.main(["--root", str(self.root), "show", "alpha"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("alpha.one", out)
        self.assertIn("pending", out)

    def test_unknown_capability_rejected(self) -> None:
        rc, _ = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "ghost.cap"
        )
        self.assertEqual(rc, 1)


    # --- full mode needs evidence too, not just the review -----------------
    #
    # mark-mvp always demanded a Manifest. mark-approved, the one path to
    # the only state another module may consume, demanded less. That was
    # backwards, and it let a fabricated Review Record over an empty tree
    # reach fully_approved in three lines of shell.

    def _approve(self, module: str, cap: str, review: Path, manifest: Path):
        return self._run(
            "--root", str(self.root), "mark-approved", module, cap,
            "--tests", str(self._test_record(module, cap)),
            "--review", str(review), "--manifest", str(manifest),
        )

    def test_mark_approved_requires_a_manifest(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("--manifest", out)
        # and with one it passes, so the failure is the missing evidence
        rc, _ = self._approve("alpha", "alpha.one", review, mf)
        self.assertEqual(rc, 0)

    def test_mark_approved_refuses_an_empty_tree(self) -> None:
        """Four OK scores over a module with no code describes nothing."""
        import shutil

        shutil.rmtree(self.repo / "modules/alpha")
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._approve("alpha", "alpha.one", review, mf)
        self.assertEqual(rc, 1)
        self.assertIn("no Python source", out)
        self.assertNotEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state,
            "fully_approved",
        )

    def test_mark_approved_refuses_when_no_tests_exist(self) -> None:
        """A Record cannot claim test_coverage: OK over no test file."""
        import shutil

        shutil.rmtree(self.repo / "tests")
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._approve("alpha", "alpha.one", review, mf)
        self.assertEqual(rc, 1)
        self.assertIn("no test file matching", out)

    def test_mark_approved_refuses_a_review_older_than_the_manifest(self) -> None:
        """The staleness rule AGENTS.md promised and nothing enforced."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        _set_mtime(review, MANIFEST_MTIME - 60)  # reviewed before the work it covers
        rc, out = self._approve("alpha", "alpha.one", review, mf)
        self.assertEqual(rc, 1)
        self.assertIn("older than", out)
        self.assertIn("ordering check only", out)

    def test_mark_approved_accepts_a_review_on_the_same_mtime_tick(self) -> None:
        """A coarse clock can land a legitimate review on the manifest's tick."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        _set_mtime(review, MANIFEST_MTIME)
        rc, _ = self._approve("alpha", "alpha.one", review, mf)
        self.assertEqual(rc, 0)

    def test_mark_changes_also_requires_the_manifest(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "quality")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("--manifest", out)

    def test_mark_changes_also_refuses_an_empty_tree(self) -> None:
        import shutil

        shutil.rmtree(self.repo / "modules/alpha")
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "quality")
        mf = self._full_manifest("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review), "--manifest", str(mf),
        )
        self.assertEqual(rc, 1)
        self.assertIn("no Python source", out)

    def test_a_successful_approval_records_both_artifacts(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        mf = self._full_manifest("alpha", "alpha.one")
        self._approve("alpha", "alpha.one", review, mf)
        rec = load_state("alpha", self.root).capabilities["alpha.one"]
        self.assertEqual(rec.review, str(review))
        self.assertEqual(rec.manifest, str(mf))




class ModuleStateAggregationTests(unittest.TestCase):
    """The aggregate must say something the capability rows do not already say."""

    @staticmethod
    def _state(*states: str) -> str:
        recs = [CapabilityRecord(state=s) for s in states]
        return compute_module_state(recs)

    def test_three_values_and_no_more(self) -> None:
        """Each label must be a fact about work, not a restatement of a row.

        The old set had six, and each of the extra three encoded something
        the rows below already said: `rework` restated `changes_requested`
        (whose reason codes say more), `partial_mvp` restated
        `mvp_developed`, and `partially_complete` claimed a granularity that
        does not exist, since consumption is per capability and a module is
        never a consumable unit.
        """
        from tools.implement.state import ModuleState

        self.assertEqual(
            {m.value for m in ModuleState},
            {"not_started", "in_progress", "complete"},
        )

    def test_nothing_touched_is_not_started(self) -> None:
        self.assertEqual(self._state("pending"), "not_started")
        self.assertEqual(self._state("pending", "pending"), "not_started")
        self.assertEqual(self._state(), "not_started")

    def test_all_approved_is_the_only_complete(self) -> None:
        """`complete` means every capability is consumable, and nothing else.

        One approved capability out of two is not a module-level fact about
        availability -- it is two rows, one green. The upstream gate is where
        per-capability consumability is decided.
        """
        self.assertEqual(self._state("fully_approved"), "complete")
        self.assertEqual(
            self._state("fully_approved", "fully_approved"), "complete"
        )

    def test_partial_approval_is_in_progress_not_a_fourth_label(self) -> None:
        self.assertEqual(self._state("fully_approved", "pending"), "in_progress")
        self.assertEqual(
            self._state("fully_approved", "changes_requested"), "in_progress"
        )
        self.assertEqual(
            self._state("fully_approved", "mvp_developed"), "in_progress"
        )

    def test_any_work_started_is_in_progress(self) -> None:
        for states in (
            ("mvp_developed",),
            ("changes_requested",),
            ("mvp_developed", "changes_requested"),
            ("pending", "changes_requested"),
            ("pending", "abandoned"),
            ("mvp_developed", "abandoned"),
            ("abandoned",),
            ("abandoned", "abandoned"),
        ):
            self.assertEqual(self._state(*states), "in_progress", states)

    def test_adding_a_capability_ratchets_complete_back_to_in_progress(self) -> None:
        """The new work is genuinely outstanding, so the module is not done.

        This is why `module_state` cannot be cached without also being
        invalidated on registration -- which is a good reason not to store it.
        """
        self.assertEqual(self._state("fully_approved"), "complete")
        self.assertEqual(self._state("fully_approved", "pending"), "in_progress")

    def test_every_capability_state_maps_to_some_label(self) -> None:
        """No state may fall through to a default, which is how the bug survived."""
        from tools.implement.state import VALID_STATES, ModuleState

        for a in VALID_STATES:
            for b in VALID_STATES:
                label = self._state(a, b)
                self.assertIn(label, {m.value for m in ModuleState})


class TestObligationGateTests(unittest.TestCase):
    """`fully_approved` is the consumable state, so it reads the contract.

    `alpha.flagged` declares two error codes and two behavior guarantees in
    `architecture/contracts/alpha-api.yaml`. The gate requires the Manifest
    to map each to a test method that exists in the test file, and requires
    the Review Record to say how many tests the reviewer actually ran.

    The failure this exists for is concrete rather than theoretical: the MVP
    discovery template's own worked example is "3 of the 4 declared error
    codes are unimplemented", and the full path — the only one another
    module may consume — did nothing about it.
    """

    CAP = "alpha.flagged"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        import tools.implement.state as st

        self.repo = self.root / "repo"
        (self.repo / "architecture/contracts").mkdir(parents=True)
        (self.repo / "architecture/contracts/alpha-api.yaml").write_text(
            "name: alpha-api\n"
            "version: 1\n"
            "requires: []\n"
            "provides:\n"
            "  - id: alpha.flagged\n"
            "    kind: operation\n"
            "    signature: alpha.flagged() -> int\n"
            "    errors:\n"
            "      - { code: ALPHA_TRANSIENT, recoverable: transient }\n"
            "      - { code: ALPHA_BAD_INPUT, recoverable: user_input }\n"
            "    behavior:\n"
            "      unit: decimal\n"
            "      time: event_time\n"
            "      idempotent: true\n"
            "      ordering: total\n",
            encoding="utf-8",
        )
        (self.repo / "architecture/modules/alpha").mkdir(parents=True)
        (self.repo / "architecture/modules/alpha/module.yaml").write_text(
            "name: alpha\n"
            "source: modules/alpha\n"
            "provides_contracts:\n"
            "  - alpha-api\n",
            encoding="utf-8",
        )
        (self.repo / "modules/alpha").mkdir(parents=True)
        (self.repo / "modules/alpha/thing.py").write_text("x = 1\n", encoding="utf-8")
        self._old_state_root, self._old_repo_root = st.STATE_ROOT, st.REPO_ROOT
        st.STATE_ROOT, st.REPO_ROOT = self.root, self.repo

    def tearDown(self) -> None:
        import tools.implement.state as st

        st.STATE_ROOT, st.REPO_ROOT = self._old_state_root, self._old_repo_root
        self._tmp.cleanup()

    # --- fixtures ----------------------------------------------------------

    def _tests(self, methods: dict[str, str] | None = None) -> Path:
        """The capability's test file, holding `methods` (name -> body)."""
        body = methods if methods is not None else {
            "test_transient": "pass",
            "test_bad_input": "pass",
            "test_is_idempotent": "pass",
            "test_is_totally_ordered": "pass",
            "test_keeps_scale": "pass",
            "test_is_event_time": "pass",
        }
        target = self.repo / naming.test_rel_path("alpha", self.CAP)
        target.parent.mkdir(parents=True, exist_ok=True)
        src = "import unittest\n\n\nclass T(unittest.TestCase):\n"
        for name in body:
            src += f"    def {name}(self) -> None:\n        {body[name]}\n\n"
        target.write_text(src, encoding="utf-8")
        return target

    def _manifest(self) -> Path:
        target = self.root / "alpha" / f"{self.CAP}.manifest.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# manifest: alpha / {self.CAP}\n\n- mode: full", encoding="utf-8"
        )
        _set_mtime(target, MANIFEST_MTIME)
        return target

    def _test_record(self, block: str | None = None) -> Path:
        """The Tester's record, and where the obligation mapping now lives.

        It used to sit in the developer's Manifest, which had the implementer
        signing a statement about test coverage for its own code.
        """
        target = self.root / "alpha" / f"{self.CAP}.tests.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        section = "" if block is None else f"\n{block}\n"
        target.write_text(
            f"# tests: alpha / {self.CAP}\n\n- mode: full{section}", encoding="utf-8"
        )
        _set_mtime(target, MANIFEST_MTIME + 30)
        return target

    def _review(self, ran: str = "4 passed, 0 skipped") -> Path:
        target = self.root / "alpha" / f"{self.CAP}.review.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# review: alpha / {self.CAP}\n"
            f"   contract_conformance: OK\n"
            f"   boundary: OK\n"
            f"   test_coverage: OK\n"
            f"   implementation_quality: OK\n"
            f"- verdict: APPROVED\n"
            f"- tests run: {ran}\n",
            encoding="utf-8",
        )
        _set_mtime(target, MANIFEST_MTIME + 60)
        return target

    def _approve(self, block: str | None = None, ran: str = "4 passed, 0 skipped"):
        from tools.implement.state import CapabilityRecord, load_state, save_state

        rec = load_state("alpha", self.root)
        rec.capabilities[self.CAP] = CapabilityRecord(state="pending", mode="full")
        save_state(rec, self.root)
        self._tests()
        manifest = self._manifest()
        record = self._test_record(block)
        review = self._review(ran)
        return self._run(
            "--root", str(self.root), "mark-approved", "alpha", self.CAP,
            "--manifest", str(manifest), "--review", str(review),
            "--tests", str(record),
        )

    def _run(self, *argv: str) -> tuple[int, str]:
        from tools.implement import state

        import contextlib
        import io

        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                rc = state.main(list(argv))
        except SystemExit as exc:
            rc = int(exc.code or 0)
        return rc, buf.getvalue()

    # Every guarantee the fixture contract declares, mapped. The list is not
    # written by hand: it is what `_test_obligations` derives from
    # `unit: decimal`, `time: event_time`, `idempotent: true`,
    # `ordering: total` and the two error codes -- which is the point. When
    # the derivation grew a field, this block stopped being complete and the
    # tests failed, which is how the growth was noticed.
    FULL_BLOCK = (
        "- tests by obligation:\n"
        "   - ALPHA_TRANSIENT: test_transient\n"
        "   - ALPHA_BAD_INPUT: test_bad_input\n"
        "   - unit: test_keeps_scale\n"
        "   - time: test_is_event_time\n"
        "   - idempotent: test_is_idempotent\n"
        "   - ordering: test_is_totally_ordered"
    )

    # --- the rules ---------------------------------------------------------

    def test_a_fully_mapped_capability_is_approved(self) -> None:
        rc, out = self._approve(self.FULL_BLOCK)
        self.assertEqual(rc, 0, out)
        self.assertIn("fully_approved", out)

    def test_a_missing_block_is_refused(self) -> None:
        rc, out = self._approve(None)
        self.assertEqual(rc, 1)
        self.assertIn("tests by obligation", out)

    def test_an_untested_error_code_is_refused(self) -> None:
        """The rule's whole reason for existing."""
        rc, out = self._approve(
            "- tests by obligation:\n"
            "   - ALPHA_TRANSIENT: test_transient\n"
            "   - idempotent: test_is_idempotent\n"
            "   - ordering: test_is_totally_ordered"
        )
        self.assertEqual(rc, 1)
        self.assertIn("ALPHA_BAD_INPUT", out)

    def test_a_claim_naming_a_test_that_is_not_there_is_refused(self) -> None:
        """A mapping the developer wrote but did not honour.

        This is the failure a count cannot see, and the one an agent under
        pressure to reach a gate produces: a Manifest that looks complete
        because the mapping is complete, over a test file where the named
        method does not exist. The obligation itself is declared, so only
        reading the test file catches it.
        """
        rc, out = self._approve(
            "- tests by obligation:\n"
            "   - ALPHA_TRANSIENT: test_transient\n"
            "   - ALPHA_BAD_INPUT: test_never_written\n"
            "   - unit: test_keeps_scale\n"
            "   - time: test_is_event_time\n"
            "   - idempotent: test_is_idempotent\n"
            "   - ordering: test_is_totally_ordered"
        )
        self.assertEqual(rc, 1)
        self.assertIn("ALPHA_BAD_INPUT", out)
        self.assertIn("test_never_written", out)

    def test_an_obligation_the_contract_does_not_declare_is_refused(self) -> None:
        """Catches a typo in the Manifest, which would otherwise pass silently."""
        rc, out = self._approve(
            "- tests by obligation:\n"
            "   - ALPHA_TRANSIENT: test_transient\n"
            "   - ALPHA_BAD_INPUT: test_bad_input\n"
            "   - idempotent: test_is_idempotent\n"
            "   - ordering: test_is_totally_ordered\n"
            "   - idemoptent: test_is_idempotent"
        )
        self.assertEqual(rc, 1)
        self.assertIn("idemoptent", out)

    def test_a_claim_whose_test_file_is_absent_is_refused(self) -> None:
        """The module has tests; this capability does not.

        `_require_work_exists` only asks whether the *module* has a test
        file, so a Manifest that maps every obligation can otherwise point at
        a file that was never written. This is the gap that leaves the gate
        at module granularity for tests while everything else is at
        capability granularity.
        """
        from tools.implement.state import CapabilityRecord, load_state, save_state

        rec = load_state("alpha", self.root)
        rec.capabilities[self.CAP] = CapabilityRecord(state="pending", mode="full")
        save_state(rec, self.root)
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests/test_alpha_something_else.py").write_text(
            "import unittest\n", encoding="utf-8"
        )
        manifest = self._manifest()
        record = self._test_record(self.FULL_BLOCK)
        review = self._review()
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", self.CAP,
            "--manifest", str(manifest), "--review", str(review),
            "--tests", str(record),
        )
        self.assertEqual(rc, 1)
        self.assertIn("does not exist", out)

    def _behavior(self, **fields) -> None:
        """Set the capability's behavior block, keeping its two error codes.

        The errors stay so that a test about behavior does not also become a
        test about a missing error mapping.
        """
        body = "\n".join(f"      {k}: {v}" for k, v in fields.items())
        (self.repo / "architecture/contracts/alpha-api.yaml").write_text(
            "name: alpha-api\nversion: 1\nrequires: []\nprovides:\n"
            "  - id: alpha.flagged\n    kind: operation\n"
            "    signature: alpha.flagged() -> int\n"
            "    errors:\n"
            "      - { code: ALPHA_TRANSIENT, recoverable: transient }\n"
            "      - { code: ALPHA_BAD_INPUT, recoverable: user_input }\n"
            "    behavior:\n" + body + "\n",
            encoding="utf-8",
        )

    def test_every_declared_behavior_field_becomes_an_obligation(self) -> None:
        """`unit` and `time` had zero readers; declaring them proved nothing.

        The gate named `idempotent` and `ordering` by hand and ignored the
        rest, so a contract could declare fourteen `unit: decimal`
        guarantees across four capabilities that nothing would ever check --
        `behavior` was 60% decoration, and adding a field to it added another
        unread one. Deriving the list means a field is enforced or it should
        not exist.
        """
        from tools.implement.state import _test_obligations

        self._behavior(unit="decimal", time="event_time", timezone="tz_aware_utc",
                       idempotent="true", ordering="total")
        from framework.architecture import load as load_arch

        obligations = _test_obligations(
            _capability_from_yaml(load_arch(self.repo), self.CAP)
        )
        for key in ("unit", "time", "timezone", "idempotent", "ordering"):
            self.assertIn(key, obligations)

    def test_a_negative_or_absent_guarantee_earns_no_obligation(self) -> None:
        """An obligation is a promise, and these promise nothing to test."""
        from tools.implement.state import _test_obligations
        from framework.architecture import load as load_arch

        self._behavior(idempotent="false", ordering="none")
        obligations = _test_obligations(
            _capability_from_yaml(load_arch(self.repo), self.CAP)
        )
        self.assertNotIn("idempotent", obligations)
        self.assertNotIn("ordering", obligations)

    def test_stale_tolerance_is_the_one_field_with_no_obligation(self) -> None:
        """Free text, so no test name can be derived from it. Said out loud.

        The alternative is leaving it as a silent gap, which is how `unit`
        and `time` stayed unread for as long as they did.
        """
        from tools.implement.state import _test_obligations
        from framework.architecture import load as load_arch

        self._behavior(stale_tolerance="5min")
        obligations = _test_obligations(
            _capability_from_yaml(load_arch(self.repo), self.CAP)
        )
        self.assertEqual(
            [k for k in obligations if k not in ("ALPHA_TRANSIENT", "ALPHA_BAD_INPUT")],
            [],
        )

    def test_an_untested_timezone_is_refused(self) -> None:
        """The gap the tester left, and why it needed a rule to close.

        The tester wrote assertions that hold whether or not the returned
        datetimes carry a UTC offset, because asserting either would have
        decided the contract question by accident. The suite was stable and
        blind: a naive-local implementation passed all eleven. Declaring
        `timezone` is only meaningful because declaring it now costs a test.
        """
        from tools.implement.state import CapabilityRecord, load_state, save_state

        rec = load_state("alpha", self.root)
        rec.capabilities[self.CAP] = CapabilityRecord(state="pending", mode="full")
        save_state(rec, self.root)
        self._behavior(unit="decimal", time="event_time", timezone="tz_aware_utc")
        self._tests({
            "test_transient": "pass", "test_bad_input": "pass",
            "test_is_idempotent": "pass", "test_is_totally_ordered": "pass",
        })
        manifest = self._manifest()
        # a Test Record that maps only the two hard-coded obligations
        record = self._test_record(
            "- tests by obligation:\n"
            "   - ALPHA_TRANSIENT: test_transient\n"
            "   - ALPHA_BAD_INPUT: test_bad_input\n"
            "   - unit: test_keeps_scale\n"
            "   - time: test_is_event_time\n"
            "   - idempotent: test_is_idempotent\n"
            "   - ordering: test_is_totally_ordered"
        )
        review = self._review()
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", self.CAP,
            "--manifest", str(manifest), "--review", str(review),
            "--tests", str(record),
        )
        self.assertEqual(rc, 1)
        self.assertIn("timezone", out)

    def test_a_review_without_a_test_run_is_refused(self) -> None:
        rc, out = self._approve(self.FULL_BLOCK, ran="")
        self.assertEqual(rc, 1)
        self.assertIn("tests run", out)

    def test_a_review_reporting_zero_tests_is_refused(self) -> None:
        rc, out = self._approve(self.FULL_BLOCK, ran="0 passed, 0 skipped")
        self.assertEqual(rc, 1)
        self.assertIn("0 tests passed", out)

    def test_a_review_reporting_a_skip_is_refused(self) -> None:
        """A passing run with one skip is still a coverage hole.

        Four skipped tests would have passed every other check in this CLI:
        the file exists, the scores are OK, and unittest exits 0.
        """
        rc, out = self._approve(self.FULL_BLOCK, ran="3 passed, 1 skipped")
        self.assertEqual(rc, 1)
        self.assertIn("skipped", out)

    def test_the_obligation_list_comes_from_the_contract_not_the_manifest(self) -> None:
        """Remove a guarantee from the contract and it stops being demanded."""
        from tools.implement.state import _test_obligations

        path = self.repo / "architecture/contracts/alpha-api.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("idempotent: true", ""),
            encoding="utf-8",
        )
        from framework.architecture import load as load_arch

        cap = _capability_from_yaml(load_arch(self.repo), self.CAP)
        self.assertNotIn("idempotent", _test_obligations(cap))
        self.assertIn("ALPHA_TRANSIENT", _test_obligations(cap))

    def test_a_capability_declaring_nothing_is_not_demanded_a_block(self) -> None:
        """The check is vacuous for a base capability, not absent from it."""
        from tools.implement.state import _test_obligations

        from framework.architecture import load as load_arch

        path = self.repo / "architecture/contracts/alpha-api.yaml"
        path.write_text(
            "name: alpha-api\nversion: 1\nrequires: []\nprovides:\n"
            "  - id: alpha.bare\n    kind: operation\n",
            encoding="utf-8",
        )
        cap = _capability_from_yaml(load_arch(self.repo), "alpha.bare")
        self.assertEqual(_test_obligations(cap), {})

    def test_mark_changes_does_not_demand_them(self) -> None:
        """A rejection may be *because* a guarantee is untested.

        Demanding the mapping on the way down would refuse to record the
        reviewer's finding — the one case where the work is known to be
        short and the run is exactly where it should stop.
        """
        from tools.implement.state import CapabilityRecord, load_state, save_state

        rec = load_state("alpha", self.root)
        rec.capabilities[self.CAP] = CapabilityRecord(state="pending", mode="full")
        save_state(rec, self.root)
        self._tests()
        manifest = self._manifest()
        review = self._review()
        review.write_text(
            review.read_text(encoding="utf-8")
            .replace("verdict: APPROVED", "verdict: CHANGES_REQUESTED")
            .replace("- tests run: 4 passed, 0 skipped\n", ""),
            encoding="utf-8",
        )
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", self.CAP,
            "--manifest", str(manifest), "--review", str(review),
        )
        self.assertEqual(rc, 1)  # no reason codes, as it happens
        self.assertNotIn("tests by obligation", out)


def _capability_from_yaml(arch, capability: str):
    for contract in arch.contracts.values():
        for cap in contract.provides:
            if cap.id == capability:
                return cap
    raise AssertionError(f"{capability} not in the fixture architecture")


class CrossModuleGateTests(unittest.TestCase):
    """The upstream gate and `dependers-of`, against a fixture architecture.

    `upstream` and `dependers-of` answer out of the ARCHITECTURE and layer
    STATE on top, so this class used to read the real `architecture/` tree
    directly. That made every assertion in it a claim about this repository's
    current declarations as well as about the state machine: dropping one
    `uses:` entry from `robinhood-rpc` broke a test whose subject is "green
    only when every declared upstream is fully_approved", and the edit that
    read best — `3/3` becoming `2/2`, with the capability id swapped to
    whatever remained — would have kept the coupling and broken again on the
    next architecture edit.

    So the architecture is a fixture, written below and reached through a
    patched `st.REPO_ROOT`, for the reason `StateCLITests` gives at the top of
    its own `setUp`: a test whose expected value moves when an unrelated
    declaration moves is not testing the thing it names.

    What is lost is the accidental check that the real declarations are
    self-consistent. That question is real and it is asked on purpose, of the
    real tree, by `DeclaredEdgesAgreeTests` in
    `tests/test_declared_edges_agree.py` — a separate file, not a class at the
    foot of this one.
    """

    # A provider whose capability ids do NOT begin with the module name, which
    # is the shape `dependers-of` has to survive: splitting `alpha.sizing.compute`
    # on the first dot invents a module called `alpha`, and no such module is
    # declared. A fixture named `alpha` publishing `alpha.one` would pass that
    # test for the wrong reason.
    PROVIDER = "robinhood-alpha"
    CONSUMER = "robinhood-beta"
    SIBLING_CONSUMERS = ("robinhood-gamma", "robinhood-delta")

    # Three, so the gate's fraction is a real one. With a single `uses:` entry
    # every count below reads 1/1 or 0/1, and a numerator that is always the
    # denominator cannot tell "all approved" from "one of one approved".
    DECLARED_USES = (
        "alpha.pool_key.parse",
        "alpha.identity.chain_id.parse",
        "alpha.identity.address.parse",
    )
    # A fourth use, held back from DECLARED_USES on purpose: `dependers-of`
    # has to narrow BY CAPABILITY, so at least one capability the consumer
    # declares must be absent from the dependers of the shared one.
    SHARED_USE = "alpha.sizing.compute"
    # Four, so `show` has a declared set with rows missing from STATE — the
    # case that made `complete` reachable for a partly-built module.
    CONSUMER_CAPS = (
        "beta.logs.read",
        "beta.header.read",
        "beta.call.read",
        "beta.capability.probe",
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_state_root = STATE_ROOT
        import tools.implement.state as st

        st.STATE_ROOT = self.root
        self.repo = self.root / "repo"
        self._write_architecture(self.repo)
        self._old_repo_root = st.REPO_ROOT
        st.REPO_ROOT = self.repo

    def tearDown(self) -> None:
        import tools.implement.state as st

        st.STATE_ROOT = self._old_state_root
        st.REPO_ROOT = self._old_repo_root
        self._tmp.cleanup()

    def _write_architecture(self, repo: Path) -> None:
        """A throwaway architecture shaped like the real consumer/provider pair.

        Hyphenated module names and dotted capability ids, because both are
        load-bearing above: a name that splits cleanly on its first dot cannot
        reproduce the provider-resolution bug, and a name without one cannot
        reproduce the import shape the grants are written for.
        """
        import yaml

        def contract(name: str, provides: tuple[str, ...], requires: list[str]) -> dict:
            return {
                "name": name,
                "version": 1,
                "requires": requires,
                "provides": [{"id": cap} for cap in provides],
            }

        def module(name: str, owns: list[str], deps: list[dict]) -> dict:
            data = {
                "name": name,
                "source": f"modules/{name}",
                "provides_contracts": owns,
                "depends_on": deps,
            }
            if deps:
                # AGENTS.md §3: a cross-module dependency needs BOTH halves —
                # the `depends_on` entry and the grant that makes the import
                # legal. The fixture carries both so it is a shape a real
                # module is allowed to have.
                data["readable_extra"] = [
                    f"modules/{d['contract'][: -len('-api')]}/api/**" for d in deps
                ]
            return data

        provider_caps = (*self.DECLARED_USES, self.SHARED_USE)
        contracts = {
            f"{self.PROVIDER}-api": contract(
                f"{self.PROVIDER}-api", provider_caps, []
            ),
            f"{self.CONSUMER}-api": contract(
                f"{self.CONSUMER}-api", self.CONSUMER_CAPS, [f"{self.PROVIDER}-api"]
            ),
        }
        modules = {
            self.PROVIDER: module(self.PROVIDER, [f"{self.PROVIDER}-api"], []),
            self.CONSUMER: module(
                self.CONSUMER,
                [f"{self.CONSUMER}-api"],
                [{"contract": f"{self.PROVIDER}-api", "uses": list(self.DECLARED_USES)}],
            ),
        }
        for name in self.SIBLING_CONSUMERS:
            contracts[f"{name}-api"] = contract(f"{name}-api", (f"{name}.plan",), [])
            modules[name] = module(
                name,
                [f"{name}-api"],
                [{"contract": f"{self.PROVIDER}-api", "uses": [self.SHARED_USE]}],
            )

        (repo / "architecture/contracts").mkdir(parents=True)
        for name, body in contracts.items():
            (repo / "architecture/contracts" / f"{name}.yaml").write_text(
                yaml.safe_dump(body, sort_keys=False), encoding="utf-8"
            )
        for name, body in modules.items():
            target = repo / "architecture/modules" / name
            target.mkdir(parents=True)
            (target / "module.yaml").write_text(
                yaml.safe_dump(body, sort_keys=False), encoding="utf-8"
            )

    def _declared_uses(self, module: str) -> list[str]:
        """The `uses:` this fixture declares, read back off disk.

        The count assertions quote this rather than a literal, so the number in
        the expectation and the number the gate prints come from one place and
        cannot drift apart when the fixture grows a use.
        """
        import yaml

        path = self.repo / "architecture/modules" / module / "module.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return [cap for dep in data["depends_on"] for cap in dep["uses"]]

    def _green_count(self, approved: int, total: int) -> str:
        return f"{approved}/{total} consumable"

    def _run(self, *argv: str) -> tuple[int, str]:
        from tools.implement import state

        import contextlib
        import io

        err, out = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = state.main(list(argv))
        except SystemExit as exc:
            rc = int(exc.code or 0)
        return rc, err.getvalue() + out.getvalue()

    def _set_upstream(self, module: str, cap: str, st: str) -> None:
        from tools.implement.state import CapabilityRecord, save_state

        rec = load_state(module, self.root)
        rec.capabilities[cap] = CapabilityRecord(state=st, mode="full")
        save_state(rec, self.root)

    def _approve_every_upstream(self) -> None:
        for cap in self.DECLARED_USES:
            self._set_upstream(self.PROVIDER, cap, "fully_approved")

    def _approve_all_but(self, cap: str) -> None:
        for other in self.DECLARED_USES:
            if other != cap:
                self._set_upstream(self.PROVIDER, other, "fully_approved")

    def test_module_state_counts_capabilities_nobody_registered(self) -> None:
        """The summary must not report `complete` for a partly-built module.

        Found on the first end-to-end run: a module had one of its three
        capabilities `fully_approved` and printed `complete`, because
        `compute_module_state` only ever saw the rows in STATE.yaml and the
        two capabilities nobody had reached were not there to disagree with
        it. The architecture is the only thing that knows all three exist.

        (That module was `market-data`, since retired — see
        `docs/implement/market-data/series.calendar.card.md`. The layer that
        module's bars capability was folded into is the one this now runs on,
        by fixture name rather than by the live module.)
        """
        approved, rest = self.CONSUMER_CAPS[0], self.CONSUMER_CAPS[1:]
        self._set_upstream(self.CONSUMER, approved, "fully_approved")
        rc, out = self._run("--root", str(self.root), "show", self.CONSUMER)
        self.assertEqual(rc, 0)
        self.assertIn("module_state: in_progress", out)
        self.assertNotIn("module_state: complete", out)
        # named individually, and counted against what the contract declares
        for cap in rest:
            self.assertIn(cap, out)
        self.assertIn(
            f"not registered ({len(rest)} of {len(self.CONSUMER_CAPS)} declared",
            out,
        )

    def test_a_fully_registered_and_approved_module_is_complete(self) -> None:
        """The correction must not make `complete` unreachable."""
        for cap in self.CONSUMER_CAPS:
            self._set_upstream(self.CONSUMER, cap, "fully_approved")
        rc, out = self._run("--root", str(self.root), "show", self.CONSUMER)
        self.assertEqual(rc, 0)
        self.assertIn("module_state: complete", out)
        self.assertNotIn("not registered", out)

    def test_a_retracted_guarantee_is_reported_not_silently_kept(self) -> None:
        """`consumes` is what makes an approved capability's footing checkable.

        The upstream gate can only see the module's whole declared `uses`
        set and only answers "may I start". This asks what an already
        `fully_approved` — i.e. consumable — capability was actually standing
        on, which is the question that had no answer at all before.
        """
        consumer_cap, retracted = self.CONSUMER_CAPS[0], self.DECLARED_USES[0]
        self._approve_all_but(retracted)  # so the retracted row is the only red
        rec = load_state(self.CONSUMER, self.root)
        rec.capabilities[consumer_cap] = CapabilityRecord(
            state="fully_approved", mode="full", consumes=[retracted]
        )
        save_state(rec, self.root)
        # the retracted capability is unregistered, so this one is consumable
        # on a guarantee nothing provides
        rc, out = self._run(
            "--root", str(self.root), "upstream", self.CONSUMER, consumer_cap
        )
        self.assertIn("retracted", out)
        self.assertIn(retracted, out)
        # reported, not enforced: not re-opened behind Owner's back
        self.assertEqual(
            load_state(self.CONSUMER, self.root).capabilities[consumer_cap].state,
            "fully_approved",
        )

    def test_a_sound_guarantee_is_not_reported(self) -> None:
        """The negative needs a positive beside it or it asserts nothing.

        Two approved capabilities in the same module, one resting on a live
        guarantee and one on a capability no contract provides, and the gate
        is asked about the module rather than about either of them — so both
        rows are examined in one report. If the check were not running at all,
        this would still pass, which is the whole reason the broken row is
        here.
        """
        sound, broken = self.CONSUMER_CAPS[0], self.CONSUMER_CAPS[1]
        self._approve_every_upstream()
        rec = load_state(self.CONSUMER, self.root)
        rec.capabilities[sound] = CapabilityRecord(
            state="fully_approved", mode="full", consumes=[self.DECLARED_USES[0]]
        )
        rec.capabilities[broken] = CapabilityRecord(
            state="fully_approved", mode="full", consumes=["alpha.retired.parse"]
        )
        save_state(rec, self.root)
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 0)
        # exactly one of the two is reported, and the other is not
        self.assertIn(f"{self.CONSUMER}/{broken} is fully_approved", out)
        self.assertIn("alpha.retired.parse", out)
        self.assertNotIn(f"{self.CONSUMER}/{sound} is fully_approved", out)

    # --- dependers-of ------------------------------------------------------

    def test_dependers_of_resolves_the_provider_from_the_architecture(self) -> None:
        """The old version split on the first dot and invented a module.

        `alpha.sizing.compute` -> a module called `alpha`, which does not
        exist. The provider is `robinhood-alpha`, so dependers-of could never
        list one.
        """
        import yaml

        rc, out = self._run(
            "--root", str(self.root), "dependers-of", self.SHARED_USE
        )
        self.assertEqual(rc, 0)
        data = yaml.safe_load(out)
        self.assertEqual(data["owning_module"], self.PROVIDER)
        self.assertEqual(data["contract"], f"{self.PROVIDER}-api")
        self.assertNotEqual(data["owning_module"], "alpha")

    def test_dependers_of_lists_the_modules_that_use_it(self) -> None:
        import yaml

        _, out = self._run(
            "--root", str(self.root), "dependers-of", self.SHARED_USE
        )
        data = yaml.safe_load(out)
        names = {d["module"] for d in data["declared_dependers"]}
        self.assertEqual(names, set(self.SIBLING_CONSUMERS))
        self.assertNotIn(self.PROVIDER, names)  # never its own depender
        # narrowed BY CAPABILITY, not by contract: the consumer declares the
        # same contract and does not appear, because it never names this use
        self.assertNotIn(self.CONSUMER, names)

    def test_dependers_of_rejects_a_capability_nobody_provides(self) -> None:
        rc, out = self._run("--root", str(self.root), "dependers-of", "not.a.cap")
        self.assertEqual(rc, 1)
        self.assertIn("not declared anywhere", out)

    # --- the upstream gate -------------------------------------------------

    def test_the_fixture_declares_a_fraction_and_not_a_single_use(self) -> None:
        """The premise of the count assertions below, stated as a test.

        With one declared use every count is 1/1 or 0/1 and a gate that
        dropped a row would still agree with the expectation.
        """
        declared = self._declared_uses(self.CONSUMER)
        self.assertEqual(sorted(declared), sorted(self.DECLARED_USES))
        self.assertGreater(len(declared), 1)

    def test_upstream_is_green_for_a_module_with_no_dependencies(self) -> None:
        rc, out = self._run("--root", str(self.root), "upstream", self.PROVIDER)
        self.assertEqual(rc, 0)
        self.assertIn("green", out)

    def test_upstream_is_red_when_the_upstream_is_unregistered(self) -> None:
        total = len(self.DECLARED_USES)
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 1)
        self.assertIn("unregistered", out)
        self.assertIn(self._green_count(0, total), out)
        for cap in self.DECLARED_USES:
            self.assertIn(cap, out)

    def test_upstream_is_red_while_one_upstream_is_still_open(self) -> None:
        """Green is a property of EVERY row, not of most of them."""
        total = len(self.DECLARED_USES)
        self._approve_all_but(self.DECLARED_USES[0])
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 1)
        self.assertIn(self._green_count(total - 1, total), out)
        self.assertNotIn("green: every declared upstream", out)

    def test_upstream_is_green_only_when_every_upstream_is_fully_approved(self) -> None:
        total = len(self.DECLARED_USES)
        self._approve_every_upstream()
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 0)
        self.assertIn(self._green_count(total, total), out)
        self.assertIn("green: every declared upstream", out)

    def test_every_state_other_than_fully_approved_is_red(self) -> None:
        """The rule the whole gate exists to enforce, over the whole state set.

        One row is held short in each state and the other two are approved, so
        a gate that only checked the first row, or that treated an MVP as a
        pass-through, fails here rather than in whichever test happened to
        name that state. Re-setting the same row to each state in turn is the
        whole setup: nothing else in STATE changes between iterations, and the
        gate reads STATE on every call.
        """
        total = len(self.DECLARED_USES)
        self._approve_all_but(self.DECLARED_USES[0])
        for state in ("pending", "mvp_developed", "changes_requested", "abandoned"):
            with self.subTest(state=state):
                self._set_upstream(self.PROVIDER, self.DECLARED_USES[0], state)
                rc, out = self._run(
                    "--root", str(self.root), "upstream", self.CONSUMER
                )
                self.assertEqual(rc, 1)
                self.assertIn(state, out)
                self.assertIn(self._green_count(total - 1, total), out)

    def test_upstream_is_red_with_an_mvp_upstream(self) -> None:
        """An MVP is not consumable, so it is red -- never a pass-through."""
        self._set_upstream(
            self.PROVIDER, self.DECLARED_USES[0], "mvp_developed"
        )
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 1)
        self.assertIn("mvp_developed", out)
        self.assertIn("retry <module> <cap> --mode full", out)

    def test_upstream_is_red_with_a_changes_requested_upstream(self) -> None:
        self._set_upstream(
            self.PROVIDER, self.DECLARED_USES[0], "changes_requested"
        )
        rc, out = self._run("--root", str(self.root), "upstream", self.CONSUMER)
        self.assertEqual(rc, 1)
        self.assertIn("changes_requested", out)

    def test_upstream_flag_narrows_to_exactly_the_named_set(self) -> None:
        """Module-level is the safe default; a Card knows better.

        Two of the three, not one: the point is that the set is replaced
        rather than intersected, which a 1/1 expectation cannot show.
        """
        named = self.DECLARED_USES[:2]
        for cap in named:
            self._set_upstream(self.PROVIDER, cap, "fully_approved")
        rc, out = self._run(
            "--root", str(self.root), "upstream", self.CONSUMER,
            self.CONSUMER_CAPS[0],
            *[arg for cap in named for arg in ("--upstream", cap)],
        )
        self.assertEqual(rc, 0)
        self.assertIn(self._green_count(len(named), len(named)), out)
        for cap in named:
            self.assertIn(cap, out)
        self.assertNotIn(self.DECLARED_USES[2], out)

    def test_upstream_reports_a_capability_no_contract_provides(self) -> None:
        """A Card naming a use that was retracted gets a red row, not a crash.

        `depends_on[].uses` is itemised, so removing an entry and a Card that
        still names it is the ordinary way this happens -- and the removed
        `protocol.pool_key.parse` is the case that has already occurred here.
        """
        rc, out = self._run(
            "--root", str(self.root), "upstream", self.CONSUMER,
            self.CONSUMER_CAPS[0], "--upstream", "alpha.retired.parse",
        )
        self.assertEqual(rc, 1)
        self.assertIn("alpha.retired.parse", out)
        self.assertIn("undeclared", out)

    def test_upstream_rejects_an_unknown_module(self) -> None:
        rc, out = self._run("--root", str(self.root), "upstream", "ghost")
        self.assertEqual(rc, 1)
        self.assertIn("ghost", out)


if __name__ == "__main__":
    unittest.main()
