"""
VM Opcode Definitions for VM Protection
"""

import random
import string
from enum import IntEnum
from typing import Dict, List, Tuple

VM_REG_COUNT = 256


def _rnd_name():
    """Generate random cryptic name for obfuscation."""
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


class Reg(IntEnum):
    """VM Registers"""
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4
    R5 = 5
    R6 = 6
    R7 = 7
    SP = 8   # Stack pointer
    BP = 9   # Base pointer
    IP = 10  # Instruction pointer
    FLAGS = 11


class Op(IntEnum):
    """VM Opcodes - base values before shuffling"""
    # Data Movement (0x00-0x1F)
    NOP = 0x00
    MOV = 0x01
    MOVI = 0x02
    LOAD = 0x03
    STORE = 0x04
    PUSH = 0x05
    POP = 0x06
    LEA = 0x07
    LOAD8 = 0x08
    STORE8 = 0x09
    LOAD16 = 0x0A
    STORE16 = 0x0B
    
    # Arithmetic (0x20-0x3F)
    ADD = 0x20
    ADDI = 0x21
    SUB = 0x22
    SUBI = 0x23
    MUL = 0x24
    DIV = 0x25
    MOD = 0x26
    NEG = 0x27
    INC = 0x28
    DEC = 0x29
    
    # Bitwise (0x40-0x5F)
    AND = 0x40
    ANDI = 0x41
    OR = 0x42
    ORI = 0x43
    XOR = 0x44
    XORI = 0x45
    NOT = 0x46
    SHL = 0x47
    SHR = 0x48
    SAR = 0x49  # Arithmetic shift right
    ROL = 0x4A
    ROR = 0x4B
    
    # Comparison & Control Flow (0x60-0x7F)
    CMP = 0x60
    CMPI = 0x61
    TEST = 0x62
    JMP = 0x70
    JZ = 0x71
    JNZ = 0x72
    JL = 0x73
    JLE = 0x74
    JG = 0x75
    JGE = 0x76
    JA = 0x77   # Jump if above (unsigned)
    JB = 0x78   # Jump if below (unsigned)
    CALL = 0x79
    RET = 0x7A
    
    # Host Interaction (0x81-0x8F)
    HLOAD = 0x81   # Load from host memory
    HSTORE = 0x82  # Store to host memory
    HARG = 0x83    # Push host call argument
    HRET = 0x84    # Get host call return value
    HPTR = 0x85    # Get host pointer
    FCALL = 0x86   # Call external function: R0 = func_table[imm](R0-R7)
    
    # Memory Management (0x90-0x9F)
    ALLOC = 0x90   # Allocate from VM heap: R0 = alloc(R0)
    FREE = 0x91    # Free VM heap: free(R0)
    CALLOC = 0x92  # Calloc from VM heap: R0 = calloc(R0, R1)
    MEMSET = 0x93  # Memset: memset(R0, R1, R2)
    MEMCPY = 0x94  # Memcpy: memcpy(R0, R1, R2)
    
    # Special (0xF0-0xFF)
    OBFUSC = 0xF0  # Self-modify trigger
    ANTDBG = 0xFE  # Anti-debug trap
    HALT = 0xFF


class OpcodeShuffler:
    """
    Shuffles opcode values per build to hinder pattern recognition.
    """
    
    def __init__(self, seed=None):
        if seed is None:
            seed = random.randint(0, 0xFFFFFFFF)
        self.seed = seed
        self.shuffle_map: Dict[int, int] = {}
        self.reverse_map: Dict[int, int] = {}
        self._generate_shuffle()
    
    def _generate_shuffle(self):
        """Generate random opcode mapping."""
        rng = random.Random(self.seed)
        
        # Keep some opcodes in their categories for handler dispatch efficiency
        used_values = set()
        
        for op in Op:
            # Generate unique random value in same category range
            base = (op.value >> 4) << 4
            candidates = [i for i in range(base, base + 16) if i not in used_values]
            
            if not candidates:
                # Fallback to any unused value
                candidates = [i for i in range(256) if i not in used_values]
            
            new_val = rng.choice(candidates)
            used_values.add(new_val)
            self.shuffle_map[op.value] = new_val
            self.reverse_map[new_val] = op.value
    
    def encode(self, op: Op) -> int:
        """Get encoded (shuffled) opcode value."""
        return self.shuffle_map.get(op.value, op.value)
    
    def decode(self, encoded: int) -> int:
        """Get original opcode from encoded value."""
        return self.reverse_map.get(encoded, encoded)
    
    def get_mapping_table(self) -> bytes:
        """Get decryption mapping table for runtime."""
        table = bytearray(256)
        for i in range(256):
            table[i] = self.reverse_map.get(i, i)
        return bytes(table)


class Instruction:
    """Represents a single VM instruction."""
    
    def __init__(self, op: Op, dst: int = 0, src1: int = 0, src2: int = 0, 
                 imm16: int = None, addr: int = None):
        self.op = op
        self.dst = dst
        self.src1 = src1
        self.src2 = src2
        self.imm16 = imm16
        self.addr = addr  # For jump targets
    
    def encode(self, shuffler: OpcodeShuffler = None) -> bytes:
        """Encode instruction to 4 bytes."""
        opcode = shuffler.encode(self.op) if shuffler else self.op.value
        
        if self.imm16 is not None:
            # Immediate format: [opcode][dst][imm16_lo][imm16_hi]
            imm = self.imm16 & 0xFFFF
            return bytes([opcode, self.dst, imm & 0xFF, (imm >> 8) & 0xFF])
        elif self.addr is not None:
            # Address format: [opcode][dst][addr_lo][addr_hi]
            addr = self.addr & 0xFFFF
            return bytes([opcode, self.dst, addr & 0xFF, (addr >> 8) & 0xFF])
        else:
            # Register format: [opcode][dst][src1][src2]
            return bytes([opcode, self.dst, self.src1, self.src2])
    
    def __repr__(self):
        if self.imm16 is not None:
            return f"{self.op.name} R{self.dst}, 0x{self.imm16:04X}"
        elif self.addr is not None:
            return f"{self.op.name} 0x{self.addr:04X}"
        else:
            return f"{self.op.name} R{self.dst}, R{self.src1}, R{self.src2}"


# Instruction builders for convenience
def mov(dst: int, src: int) -> Instruction:
    return Instruction(Op.MOV, dst=dst, src1=src)

def movi(dst: int, imm: int) -> Instruction:
    return Instruction(Op.MOVI, dst=dst, imm16=imm)

def load(dst: int, addr_reg: int) -> Instruction:
    return Instruction(Op.LOAD, dst=dst, src1=addr_reg)

def store(addr_reg: int, src: int) -> Instruction:
    return Instruction(Op.STORE, dst=addr_reg, src1=src)

def push(src: int) -> Instruction:
    return Instruction(Op.PUSH, src1=src)

def pop(dst: int) -> Instruction:
    return Instruction(Op.POP, dst=dst)

def add(dst: int, src1: int, src2: int) -> Instruction:
    return Instruction(Op.ADD, dst=dst, src1=src1, src2=src2)

def addi(dst: int, src: int, imm: int) -> Instruction:
    return Instruction(Op.ADDI, dst=dst, src1=src, imm16=imm)

def sub(dst: int, src1: int, src2: int) -> Instruction:
    return Instruction(Op.SUB, dst=dst, src1=src1, src2=src2)

def mul(dst: int, src1: int, src2: int) -> Instruction:
    return Instruction(Op.MUL, dst=dst, src1=src1, src2=src2)

def xor(dst: int, src1: int, src2: int) -> Instruction:
    return Instruction(Op.XOR, dst=dst, src1=src1, src2=src2)

def cmp(src1: int, src2: int) -> Instruction:
    return Instruction(Op.CMP, src1=src1, src2=src2)

def jmp(addr: int) -> Instruction:
    return Instruction(Op.JMP, addr=addr)

def jz(addr: int) -> Instruction:
    return Instruction(Op.JZ, addr=addr)

def jnz(addr: int) -> Instruction:
    return Instruction(Op.JNZ, addr=addr)

def call(addr: int) -> Instruction:
    return Instruction(Op.CALL, addr=addr)

def ret() -> Instruction:
    return Instruction(Op.RET)

def alloc() -> Instruction:
    return Instruction(Op.ALLOC)

def free_mem() -> Instruction:
    return Instruction(Op.FREE)

def calloc_mem() -> Instruction:
    return Instruction(Op.CALLOC)

def halt() -> Instruction:
    return Instruction(Op.HALT)
