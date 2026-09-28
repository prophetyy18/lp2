"""Implementation state machine.

States per capability:

    pending           planned, no implementation
    mvp_developed     MVP implementation exists, NOT reviewed (does not count as done)
    fully_approved    implementation reviewed and approved (this counts as done)
    changes_requested reviewer rejected, developer must iterate
    abandoned         owner closed this capability

Transitions are mechanical (state.py). The dispatcher decides when to fire
which transition; this package only validates them.
"""

from .state import STATE_ROOT, CapabilityState, ModuleState, load_state, save_state

__all__ = [
    "STATE_ROOT",
    "CapabilityState",
    "ModuleState",
    "load_state",
    "save_state",
]