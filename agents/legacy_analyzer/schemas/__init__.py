"""Schemas for legacy analyzer agent."""

from agents.legacy_analyzer.schemas.assessment import (
    AcceptIO,
    CallDependency,
    CallMenuOption,
    ControlFlowConstruct,
    DataField,
    DisplayIO,
    DisplayMenuOption,
    EvaluateConstruct,
    IOOperation,
    LegacyAssessment,
    MenuOption,
    PerformUntilConstruct,
    ProgramIdentity,
    SourceEvidence,
    StopRunConstruct,
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
    "AcceptIO",
    "CallDependency",
    "CallMenuOption",
    "ControlFlowConstruct",
    "DataField",
    "DisplayIO",
    "DisplayMenuOption",
    "EvaluateConstruct",
    "IOOperation",
    "LegacyAssessment",
    "LegacyAssessmentV1",
    "MenuOption",
    "ModernizationObservationV1",
    "PerformUntilConstruct",
    "ProgramIdentity",
    "ScopeDeclarationV1",
    "SourceEvidence",
    "StopRunConstruct",
]
