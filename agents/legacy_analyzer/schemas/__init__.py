"""Schemas for legacy analyzer agent."""

from agents.legacy_analyzer.schemas.assessment import (
    CallDependency,
    ControlFlowConstruct,
    DataField,
    IOOperation,
    LegacyAssessment,
    MenuOption,
    ProgramIdentity,
    SourceEvidence,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    LegacyAssessment as LegacyAssessmentV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ModernizationObservation as ModernizationObservationV1,
)
from agents.legacy_analyzer.schemas.assessment_v1 import (
    ScopeDeclaration as ScopeDeclarationV1,
)

__all__ = [
    "CallDependency",
    "ControlFlowConstruct",
    "DataField",
    "IOOperation",
    "LegacyAssessment",
    "LegacyAssessmentV1",
    "MenuOption",
    "ModernizationObservationV1",
    "ProgramIdentity",
    "ScopeDeclarationV1",
    "SourceEvidence",
]
