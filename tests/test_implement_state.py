"""Capability state machine: transitions, mode rules, aggregated state."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        rec.module_state = compute_module_state(rec.capabilities.values())
        self.assertEqual(rec.module_state, "partial_mvp")

    def test_only_mvp_can_be_fully_approved(self) -> None:
        # pending -> fully_approved is allowed (full mode path)
        rec = self._record()
        rec.capabilities["alpha.one"].state = "fully_approved"
        self.assertEqual(
            compute_module_state(rec.capabilities.values()), "partially_complete"
        )

    def test_full_approval_for_all_capabilities_makes_module_complete(self) -> None:
        rec = ModuleRecord(
            name="alpha",
            capabilities={
                "alpha.one": CapabilityRecord(state="fully_approved", mode="full"),
                "alpha.two": CapabilityRecord(state="fully_approved", mode="full"),
            },
        )
        rec.module_state = compute_module_state(rec.capabilities.values())
        self.assertEqual(rec.module_state, "complete")

    def test_pending_only_module_is_planned(self) -> None:
        rec = self._record()
        self.assertEqual(compute_module_state(rec.capabilities.values()), "planned")

    def test_all_abandoned_makes_module_abandoned(self) -> None:
        rec = ModuleRecord(
            name="alpha",
            capabilities={
                "alpha.one": CapabilityRecord(state="abandoned"),
                "alpha.two": CapabilityRecord(state="abandoned"),
            },
        )
        self.assertEqual(compute_module_state(rec.capabilities.values()), "abandoned")

    def test_round_trip_yaml(self) -> None:
        rec = self._record()
        rec.capabilities["alpha.one"].state = "mvp_developed"
        rec.capabilities["alpha.one"].manifest = "manifests/one.md"
        path = save_state(rec, self.root)
        loaded = load_state("alpha", self.root)
        self.assertEqual(loaded.capabilities["alpha.one"].state, "mvp_developed")
        self.assertEqual(loaded.capabilities["alpha.one"].manifest, "manifests/one.md")
        self.assertEqual(loaded.module_state, "partial_mvp")

    def test_load_missing_module_yields_empty_record(self) -> None:
        rec = load_state("ghost", self.root)
        self.assertEqual(rec.name, "ghost")
        self.assertEqual(rec.capabilities, {})

    def test_module_state_default_is_planned(self) -> None:
        rec = ModuleRecord(name="empty")
        self.assertEqual(compute_module_state(rec.capabilities.values()), "planned")


class StateCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old_state_root = STATE_ROOT
        # Redirect by patching the constant used by the CLI imports.
        import tools.implement.state as st

        st.STATE_ROOT = self.root

    def tearDown(self) -> None:
        import tools.implement.state as st

        st.STATE_ROOT = self._old_state_root
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

    def _review(
        self,
        module: str,
        cap: str,
        verdict: str = "APPROVED",
        reasons: str | None = None,
        scores: tuple[str, ...] = ("OK", "OK", "OK", "OK"),
    ) -> Path:
        """Write a Review Record that the state CLI will accept."""
        target = self.root / module / f"{cap}.review.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        reason_line = (
            f"- reason codes: [{reasons}]\n" if reasons is not None else ""
        )
        target.write_text(
            f"# review: {module} / {cap}\n"
            f"   contract_conformance: {scores[0]}\n"
            f"   boundary: {scores[1]}\n"
            f"   test_coverage: {scores[2]}\n"
            f"   implementation_quality: {scores[3]}\n"
            f"{reason_line}"
            f"- verdict: {verdict}\n",
            encoding="utf-8",
        )
        return target

    def _blocker(self, module: str, cap: str) -> Path:
        target = self.root / module / f"{cap}.design-blocker.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# design blocker: {module} / {cap}\n\n"
            f"the contract declares only RPC_TIMEOUT; the node returns\n"
            f"execution_reverted, so the error surface is wider than designed.\n",
            encoding="utf-8",
        )
        return target

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
        review = self.root / "alpha" / "alpha.one.review.md"
        review.write_text(
            "# review: alpha / alpha.one\n"
            "   contract_conformance: OK\n"
            "   boundary: OK\n"
            "   test_coverage: OK\n"
            "   implementation_quality: OK\n"
            "- verdict: APPROVED\n",
            encoding="utf-8",
        )
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 0)
        self.assertIn("fully_approved", out)

    def test_mark_approved_is_refused_from_mvp_developed(self) -> None:
        """An MVP is never consumable; it cannot reach fully_approved in place."""
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        rc, out = self._run("--root", str(self.root), "mark-approved", "alpha", "alpha.one")
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
        )
        rc, _ = self._run("--root", str(self.root), "retry", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / "alpha" / "alpha.one.mvp-manifest.md").exists())

    # --- mark-changes must record what it rejected, and why -----------------

    def test_mark_changes_records_the_review_path(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "boundary")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 0)
        self.assertIn("boundary", out)
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].review, str(review))

    def test_mark_changes_requires_a_review(self) -> None:
        self._seed("alpha", "alpha.one")
        rc, out = self._run("--root", str(self.root), "mark-changes", "alpha", "alpha.one")
        self.assertEqual(rc, 1)
        self.assertIn("--review", out)

    def test_mark_changes_rejects_an_approved_review(self) -> None:
        """Recording a rejection on top of an APPROVED record would be nonsense."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED", "quality")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("CHANGES_REQUESTED", out)

    def test_mark_changes_requires_at_least_one_reason(self) -> None:
        """A rejection the developer cannot act on sends them back to guessing."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", reasons="")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("reason code", out)

    def test_mark_changes_rejects_an_unknown_reason_code(self) -> None:
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "CHANGES_REQUESTED", "vibes")
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("vibes", out)

    # --- an open design blocker outranks every gate -------------------------

    def test_mark_approved_is_refused_while_a_design_blocker_is_open(self) -> None:
        """A stale blocker must not be able to coexist with fully_approved."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        self._blocker("alpha", "alpha.one")
        rc, out = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
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
        rc, out = self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 1)
        self.assertIn("design blocker", out)

    def test_a_resolved_blocker_no_longer_gates(self) -> None:
        """Resolution is recorded by renaming the file, so the check is the file."""
        self._seed("alpha", "alpha.one")
        review = self._review("alpha", "alpha.one", "APPROVED")
        blocker = self._blocker("alpha", "alpha.one")
        blocker.rename(blocker.with_name("alpha.one.design-blocker.resolved.md"))
        rc, _ = self._run(
            "--root", str(self.root), "mark-approved", "alpha", "alpha.one",
            "--review", str(review),
        )
        self.assertEqual(rc, 0)

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


class ModuleStateAggregationTests(unittest.TestCase):
    """The aggregate label must not claim more than the capabilities show."""

    @staticmethod
    def _state(*states: str) -> str:
        recs = [CapabilityRecord(state=s) for s in states]
        return compute_module_state(recs)

    def test_every_rejected_capability_is_rework_not_partial_mvp(self) -> None:
        # the misclassification: an MVP label for work that has none
        self.assertEqual(self._state("changes_requested"), "rework")
        self.assertEqual(
            self._state("changes_requested", "changes_requested"), "rework"
        )

    def test_rejected_alongside_other_work_is_rework(self) -> None:
        self.assertEqual(
            self._state("pending", "changes_requested"), "rework"
        )
        self.assertEqual(
            self._state("mvp_developed", "changes_requested"), "rework"
        )

    def test_rejected_alongside_an_approved_capability_is_partially_complete(self) -> None:
        # one consumable capability is the more useful fact than the rejection
        self.assertEqual(
            self._state("fully_approved", "changes_requested"),
            "partially_complete",
        )

    def test_abandoned_mixed_with_pending_is_planned(self) -> None:
        # not partial_mvp, and not abandoned: the owner closed one, work remains
        self.assertEqual(self._state("abandoned", "pending"), "planned")

    def test_mvp_alone_or_mixed_is_partial_mvp(self) -> None:
        self.assertEqual(self._state("mvp_developed"), "partial_mvp")
        self.assertEqual(self._state("mvp_developed", "pending"), "partial_mvp")
        self.assertEqual(self._state("mvp_developed", "abandoned"), "partial_mvp")

    def test_approved_alongside_anything_else_is_partially_complete(self) -> None:
        for other in ("pending", "mvp_developed", "abandoned"):
            self.assertEqual(
                self._state("fully_approved", other), "partially_complete"
            )

    def test_uniform_states(self) -> None:
        self.assertEqual(self._state("pending"), "planned")
        self.assertEqual(self._state("fully_approved"), "complete")
        self.assertEqual(self._state("abandoned"), "abandoned")

    def test_every_capability_state_maps_to_some_label(self) -> None:
        """No state may fall through to a default, which is how the bug survived."""
        from tools.implement.state import VALID_STATES, ModuleState

        for a in VALID_STATES:
            for b in VALID_STATES:
                label = self._state(a, b)
                self.assertIn(label, {m.value for m in ModuleState})


class CrossModuleGateTests(unittest.TestCase):
    """`upstream` and `dependers-of` read the real architecture, not STATE guesses."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

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

    # --- dependers-of ------------------------------------------------------

    def test_dependers_of_resolves_the_provider_from_the_architecture(self) -> None:
        """The old version split on the first dot and invented a module.

        `series.get` -> a module called `series`, which does not exist. The
        provider is market-data, so dependers-of could never list one.
        """
        import yaml

        rc, out = self._run("--root", str(self.root), "dependers-of", "series.get")
        self.assertEqual(rc, 0)
        data = yaml.safe_load(out)
        self.assertEqual(data["owning_module"], "market-data")
        self.assertEqual(data["contract"], "market-data-api")
        self.assertNotEqual(data["owning_module"], "series")

    def test_dependers_of_lists_the_modules_that_use_it(self) -> None:
        import yaml

        _, out = self._run("--root", str(self.root), "dependers-of", "series.get")
        data = yaml.safe_load(out)
        names = {d["module"] for d in data["declared_dependers"]}
        self.assertIn("backtest", names)
        self.assertIn("pricing", names)
        self.assertNotIn("market-data", names)  # never its own depender

    def test_dependers_of_rejects_a_capability_nobody_provides(self) -> None:
        rc, out = self._run("--root", str(self.root), "dependers-of", "not.a.cap")
        self.assertEqual(rc, 1)
        self.assertIn("not declared anywhere", out)

    # --- the upstream gate -------------------------------------------------

    def test_upstream_is_green_for_a_module_with_no_dependencies(self) -> None:
        rc, out = self._run("--root", str(self.root), "upstream", "market-data")
        self.assertEqual(rc, 0)
        self.assertIn("green", out)

    def test_upstream_is_red_when_the_upstream_is_unregistered(self) -> None:
        rc, out = self._run("--root", str(self.root), "upstream", "backtest")
        self.assertEqual(rc, 1)
        self.assertIn("series.get", out)
        self.assertIn("unregistered", out)

    def test_upstream_is_green_only_when_every_upstream_is_fully_approved(self) -> None:
        for cap in ("series.get", "series.calendar"):
            self._set_upstream("market-data", cap, "fully_approved")
        for cap in ("position.mark", "pricing.quote"):
            self._set_upstream("pricing", cap, "fully_approved")
        rc, out = self._run("--root", str(self.root), "upstream", "backtest")
        self.assertEqual(rc, 0)
        self.assertIn("4/4 consumable", out)

    def test_upstream_is_red_with_an_mvp_upstream(self) -> None:
        """An MVP is not consumable, so it is red -- never a pass-through."""
        for cap in ("position.mark", "pricing.quote"):
            self._set_upstream("pricing", cap, "fully_approved")
        self._set_upstream("market-data", "series.get", "mvp_developed")
        self._set_upstream("market-data", "series.calendar", "fully_approved")
        rc, out = self._run("--root", str(self.root), "upstream", "backtest")
        self.assertEqual(rc, 1)
        self.assertIn("mvp_developed", out)
        self.assertIn("retry <module> <cap> --mode full", out)

    def test_upstream_is_red_with_a_changes_requested_upstream(self) -> None:
        self._set_upstream("market-data", "series.get", "changes_requested")
        rc, out = self._run("--root", str(self.root), "upstream", "backtest")
        self.assertEqual(rc, 1)
        self.assertIn("changes_requested", out)

    def test_upstream_flag_narrows_the_declared_set(self) -> None:
        """Module-level is the safe default; a Card knows better."""
        self._set_upstream("market-data", "series.get", "fully_approved")
        rc, out = self._run(
            "--root", str(self.root), "upstream", "backtest", "backtest.run",
            "--upstream", "series.get",
        )
        self.assertEqual(rc, 0)
        self.assertIn("1/1 consumable", out)
        self.assertNotIn("series.calendar", out)

    def test_upstream_rejects_an_unknown_module(self) -> None:
        rc, out = self._run("--root", str(self.root), "upstream", "ghost")
        self.assertEqual(rc, 1)
        self.assertIn("ghost", out)


if __name__ == "__main__":
    unittest.main()
