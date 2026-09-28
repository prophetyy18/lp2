"""Architecture framework (V0).

An independent subsystem that answers three questions about module isolation:

    readable()      - what may this module read?
    dependencies()  - what may this module depend on?
    blast_radius()  - who is affected if this contract changes?

It depends on nothing from the project and nothing from any future workflow:
dependency direction is future workflow -> architecture framework.
"""

from .boundary import check_read, check_read_many, readable_rules
from .errors import (
    ARCHITECTURE_CHANGE_REQUIRED,
    BOUNDARY_VIOLATION,
    CONTRACT_INSUFFICIENT,
    ILLEGAL_DEPENDENCY,
    ArchError,
    ContractInsufficient,
    Finding,
)
from .graph import consumers, direct_module_edges, owners, reverse_contracts
from .impact import ImpactResult, impact_of_contract, impact_of_module
from .loader import find_root, load
from .model import Architecture, Capability, Contract, Dependency, Module
from .query import (
    blast_radius,
    check_paths,
    consumers_of,
    dependencies,
    impact_of_diff,
    readable,
    validation_report,
)
from .validator import has_errors, validate

__all__ = [
    "Architecture",
    "ArchError",
    "ARCHITECTURE_CHANGE_REQUIRED",
    "BOUNDARY_VIOLATION",
    "Capability",
    "CONTRACT_INSUFFICIENT",
    "Contract",
    "ContractInsufficient",
    "Dependency",
    "Finding",
    "ILLEGAL_DEPENDENCY",
    "ImpactResult",
    "Module",
    "blast_radius",
    "check_paths",
    "check_read",
    "check_read_many",
    "consumers",
    "consumers_of",
    "dependencies",
    "direct_module_edges",
    "find_root",
    "has_errors",
    "impact_of_contract",
    "impact_of_diff",
    "impact_of_module",
    "load",
    "owners",
    "readable",
    "readable_rules",
    "reverse_contracts",
    "validate",
    "validation_report",
]
