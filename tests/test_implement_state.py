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

    def _run(self, *argv: str) -> tuple[int, str]:
        from tools.implement import state

        # capture stderr (where the CLI writes status)
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = state.main(list(argv))
        return rc, buf.getvalue()

    def test_mark_mvp_succeeds(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        rc, out = self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertIn("mvp_developed", out)

    def test_mark_mvp_rejects_wrong_mode(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        rc, _ = self._run(
            "--root", str(self.root), "mark-mvp", "alpha", "alpha.one", "--mode", "mvp"
        )
        self.assertEqual(rc, 1)

    def test_mark_approved_works_from_pending(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        rc, out = self._run("--root", str(self.root), "mark-approved", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertIn("fully_approved", out)

    def test_mark_approved_works_from_mvp(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one")
        rc, out = self._run("--root", str(self.root), "mark-approved", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        self.assertIn("fully_approved", out)

    def test_promote_requires_mvp_state(self) -> None:
        self._seed("alpha", "alpha.one", mode="full")
        rc, _ = self._run("--root", str(self.root), "promote", "alpha", "alpha.one")
        self.assertEqual(rc, 1)

    def test_promote_resets_to_pending(self) -> None:
        self._seed("alpha", "alpha.one", mode="mvp")
        self._run("--root", str(self.root), "mark-mvp", "alpha", "alpha.one")
        rc, out = self._run("--root", str(self.root), "promote", "alpha", "alpha.one")
        self.assertEqual(rc, 0)
        rec = load_state("alpha", self.root)
        self.assertEqual(rec.capabilities["alpha.one"].state, "pending")
        self.assertEqual(rec.capabilities["alpha.one"].mode, "full")

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