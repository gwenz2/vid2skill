"""
vid2skill - Universal agent skill synthesis, validation, and testing framework.
"""

__version__ = "1.0.0"

from .core.extractor import extract_content, clean_transcript
from .core.synthesizer import synthesize_skill, SkillBundle
from .core.validator import validate_skill_dir, ValidationResult
from .core.evaluator import evaluate_triggers, EvaluationReport
from .core.improver import improve_skill

__all__ = [
    "extract_content",
    "clean_transcript",
    "synthesize_skill",
    "SkillBundle",
    "validate_skill_dir",
    "ValidationResult",
    "evaluate_triggers",
    "EvaluationReport",
    "improve_skill",
]
