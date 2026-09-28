"""Cross-module import isolation scanner.

Walks `modules/<M>/**/*.py`, parses each file's AST, and reports every
`import` / `from ... import` statement that crosses a module boundary.
Pure module consumption must go through the architecture contract; this
tool is the enforcement layer below the architecture framework's
`readable_extra` rule.
"""

from .scan import Finding, scan_module, scan_repo

__all__ = ["Finding", "scan_module", "scan_repo"]