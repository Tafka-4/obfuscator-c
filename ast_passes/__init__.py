"""
AST-based obfuscation passes.
All passes use Clang AST for precise transformation.
"""

from .base import ASTBasePass
from .opaque_pred import OpaquePredicates
from .mba import MBAPass
from .insn_subst import InstructionSubstitution
from .bogus_cff import BogusControlFlow
from .graph_split import GraphSplit

__all__ = [
    'ASTBasePass',
    'OpaquePredicates',
    'MBAPass',
    'InstructionSubstitution',
    'BogusControlFlow',
    'GraphSplit',
]
