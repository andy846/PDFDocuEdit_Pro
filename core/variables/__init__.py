"""Shared, headless and declarative variable resolution."""

from .model import VariableContext, VariableError
from .parser import compile_template
from .paths import plan_outputs, resolve_filename, validate_filename
from .resolver import resolve, validate_dependencies

__all__ = [
    "VariableContext", "VariableError", "compile_template", "resolve",
    "validate_dependencies", "resolve_filename", "validate_filename", "plan_outputs",
]
