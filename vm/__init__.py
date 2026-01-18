"""
VM Protection Module
"""

from .opcodes import Op, Reg, Instruction, OpcodeShuffler
from .emitter import BytecodeEmitter, BytecodeBuilder, Label
from .runtime import VMRuntimeGenerator, generate_vm_runtime
from .compiler import ASTCompiler, CompilerContext


__all__ = [
    'Op', 'Reg', 'Instruction', 'OpcodeShuffler',
    'BytecodeEmitter', 'BytecodeBuilder', 'Label',
    'VMRuntimeGenerator', 'generate_vm_runtime',
    'ASTCompiler', 'CompilerContext',
]
