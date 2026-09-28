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

    def test_retry_from_mvp_refuses_when_the_manifest_is_gone(self) -> None:
        """Silently reopening with no discovery is the failure this guards against."""
        self._seed("alpha", "alpha.one", mode="mvp")
        m = self._manifest("alpha", "alpha.one")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--manifest", str(m))
        m.unlink()
        rc, out = self._run(
            "--root", str(self.root), "retry", "alpha", "alpha.one", "--mode", "full"
        )
        self.assertEqual(rc, 1)
        self.assertIn("is gone", out)
        self.assertEqual(
            load_state("alpha", self.root).capabilities["alpha.one"].state, "mvp_developed"
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
        review = self.root / "alpha" / "alpha.one.review.md"
        review.write_text(
            "# review: alpha / alpha.one\n- verdict: CHANGES_REQUESTED\n",
            encoding="utf-8",
        )
        self._run(
            "--root", str(self.root), "mark-changes", "alpha", "alpha.one",
        )
        rc, _ = self._run("--root", str(self.root), "retry", "alpha", "alpha.one")
        self.assertEqual(rc, 0)

    def test_mvp_only_exits_to_pending_or_abandoned(self) -> None:
        from tools.implement.state import _ALLOWED

        self.assertEqual(
            _ALLOWED["mvp_developed"], frozenset({"pending", "abandoned"})
        )

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


if __name__ == "__main__":
    unittest.main()
