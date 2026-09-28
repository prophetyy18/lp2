"""State machine errors."""


class StateError(Exception):
    """A state transition or command is invalid.

    The CLI returns exit code 1 on StateError so CI / dispatchers can branch
    on the exit status alone without parsing message text.
    """