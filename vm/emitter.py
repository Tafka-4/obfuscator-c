"""
VM Bytecode Emitter
"""

import random
import string
from typing import List, Dict, Tuple, Optional
from .opcodes import Op, Reg, Instruction, OpcodeShuffler


def _rnd_name():
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


class Label:
    """Represents a label for jump targets."""
    def __init__(self, name: str = None):
        self.name = name or _rnd_name()
        self.address: Optional[int] = None


class BytecodeEmitter:
    """
    Emits VM bytecode from high-level instructions.
    Handles label resolution and encryption.
    """
    
    def __init__(self, shuffler: OpcodeShuffler = None):
        self.instructions: List[Instruction] = []
        self.labels: Dict[str, Label] = {}
        self.pending_jumps: List[Tuple[int, str]] = []  # (instr_idx, label_name)
        self.shuffler = shuffler or OpcodeShuffler()
        self.tea_key = [random.getrandbits(32) for _ in range(4)]
        self.tea_nonce = random.getrandbits(64)
    
    def label(self, name: str = None) -> Label:
        """Create and register a label at current position."""
        lbl = Label(name)
        lbl.address = len(self.instructions) * 4  # Each instruction is 4 bytes
        self.labels[lbl.name] = lbl
        return lbl
    
    def emit(self, instr: Instruction):
        """Emit a single instruction."""
        self.instructions.append(instr)
    
    def emit_jmp(self, op: Op, label: Label):
        """Emit a jump instruction with pending label resolution."""
        idx = len(self.instructions)
        self.instructions.append(Instruction(op, addr=0xFFFF))  # Placeholder
        self.pending_jumps.append((idx, label.name))
    
    # High-level emission helpers
    def emit_mov(self, dst: int, src: int):
        self.emit(Instruction(Op.MOV, dst=dst, src1=src))
    
    def emit_movi(self, dst: int, imm: int):
        self.emit(Instruction(Op.MOVI, dst=dst, imm16=imm))
    
    def emit_load(self, dst: int, addr_reg: int):
        self.emit(Instruction(Op.LOAD, dst=dst, src1=addr_reg))

    def emit_store(self, addr_reg: int, src: int):
        self.emit(Instruction(Op.STORE, dst=addr_reg, src1=src))

    def emit_load8(self, dst: int, addr_reg: int):
        self.emit(Instruction(Op.LOAD8, dst=dst, src1=addr_reg))

    def emit_store8(self, addr_reg: int, src: int):
        self.emit(Instruction(Op.STORE8, dst=addr_reg, src1=src))

    def emit_load16(self, dst: int, addr_reg: int):
        self.emit(Instruction(Op.LOAD16, dst=dst, src1=addr_reg))

    def emit_store16(self, addr_reg: int, src: int):
        self.emit(Instruction(Op.STORE16, dst=addr_reg, src1=src))
    
    def emit_push(self, src: int):
        self.emit(Instruction(Op.PUSH, src1=src))
    
    def emit_pop(self, dst: int):
        self.emit(Instruction(Op.POP, dst=dst))
    
    def emit_add(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.ADD, dst=dst, src1=src1, src2=src2))
    
    def emit_addi(self, dst: int, src: int, imm: int):
        self.emit(Instruction(Op.ADDI, dst=dst, src1=src, imm16=imm))
    
    def emit_sub(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.SUB, dst=dst, src1=src1, src2=src2))
    
    def emit_mul(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.MUL, dst=dst, src1=src1, src2=src2))
    
    def emit_div(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.DIV, dst=dst, src1=src1, src2=src2))
    
    def emit_and(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.AND, dst=dst, src1=src1, src2=src2))
    
    def emit_or(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.OR, dst=dst, src1=src1, src2=src2))
    
    def emit_xor(self, dst: int, src1: int, src2: int):
        self.emit(Instruction(Op.XOR, dst=dst, src1=src1, src2=src2))
    
    def emit_not(self, dst: int, src: int):
        self.emit(Instruction(Op.NOT, dst=dst, src1=src))
    
    def emit_shl(self, dst: int, src: int, n: int):
        self.emit(Instruction(Op.SHL, dst=dst, src1=src, src2=n))
    
    def emit_shr(self, dst: int, src: int, n: int):
        self.emit(Instruction(Op.SHR, dst=dst, src1=src, src2=n))
    
    def emit_cmp(self, src1: int, src2: int):
        self.emit(Instruction(Op.CMP, src1=src1, src2=src2))
    
    def emit_jmp(self, label: Label):
        self._emit_jump(Op.JMP, label)
    
    def emit_jz(self, label: Label):
        self._emit_jump(Op.JZ, label)
    
    def emit_jnz(self, label: Label):
        self._emit_jump(Op.JNZ, label)
    
    def emit_jl(self, label: Label):
        self._emit_jump(Op.JL, label)
    
    def emit_jle(self, label: Label):
        self._emit_jump(Op.JLE, label)
    
    def emit_jg(self, label: Label):
        self._emit_jump(Op.JG, label)
    
    def emit_jge(self, label: Label):
        self._emit_jump(Op.JGE, label)
    
    def emit_call(self, label: Label):
        self._emit_jump(Op.CALL, label)
    
    def emit_ret(self):
        self.emit(Instruction(Op.RET))
    
    def emit_halt(self):
        self.emit(Instruction(Op.HALT))
    
    # Memory management operations
    def emit_alloc(self):
        """Emit ALLOC: R0 = alloc(R0)"""
        self.emit(Instruction(Op.ALLOC))
    
    def emit_free(self):
        """Emit FREE: free(R0)"""
        self.emit(Instruction(Op.FREE))
    
    def emit_calloc(self):
        """Emit CALLOC: R0 = calloc(R0, R1)"""
        self.emit(Instruction(Op.CALLOC))
    
    def emit_memset(self):
        """Emit MEMSET: memset(R0, R1, R2)"""
        self.emit(Instruction(Op.MEMSET))
    
    def emit_memcpy(self):
        """Emit MEMCPY: memcpy(R0, R1, R2)"""
        self.emit(Instruction(Op.MEMCPY))
    
    def emit_fcall(self, func_idx: int):
        """Emit FCALL: R0 = func_table[func_idx](R0-R7)"""
        self.emit(Instruction(Op.FCALL, dst=func_idx))
    
    def _emit_jump(self, op: Op, label: Label):
        """Internal: emit jump with label resolution."""
        idx = len(self.instructions)
        self.instructions.append(Instruction(op, addr=0xFFFF))
        self.pending_jumps.append((idx, label.name))
    
    def _resolve_labels(self):
        """Resolve all pending jump targets."""
        for idx, label_name in self.pending_jumps:
            if label_name not in self.labels:
                raise ValueError(f"Undefined label: {label_name}")
            
            target_addr = self.labels[label_name].address
            instr = self.instructions[idx]
            instr.addr = target_addr
    
    def _tea_encrypt_block(self, v0: int, v1: int) -> Tuple[int, int]:
        """Encrypt a single 64-bit block using TEA (returns v0, v1)."""
        delta = 0x9E3779B9
        sum_val = 0
        k0, k1, k2, k3 = self.tea_key
        for _ in range(32):
            sum_val = (sum_val + delta) & 0xFFFFFFFF
            v0 = (v0 + (((v1 << 4) + k0) ^ (v1 + sum_val) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
            v1 = (v1 + (((v0 << 4) + k2) ^ (v0 + sum_val) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
        return v0, v1

    def _encrypt_bytecode(self, data: bytes) -> bytes:
        """Encrypt bytecode using TEA-CTR (XOR with TEA keystream)."""
        result = bytearray(len(data))
        block = 0
        offset = 0
        while offset < len(data):
            counter = (self.tea_nonce + block) & 0xFFFFFFFFFFFFFFFF
            v0 = counter & 0xFFFFFFFF
            v1 = (counter >> 32) & 0xFFFFFFFF
            k0, k1 = self._tea_encrypt_block(v0, v1)
            ks = k0.to_bytes(4, "little") + k1.to_bytes(4, "little")
            for i in range(8):
                if offset + i >= len(data):
                    break
                result[offset + i] = data[offset + i] ^ ks[i]
            offset += 8
            block += 1
        return bytes(result)
    
    def finalize(self, encrypt: bool = True) -> bytes:
        """Finalize and return bytecode."""
        self._resolve_labels()
        
        # Encode all instructions
        bytecode = bytearray()
        for instr in self.instructions:
            bytecode.extend(instr.encode(self.shuffler))
        
        if encrypt:
            bytecode = self._encrypt_bytecode(bytes(bytecode))
        
        return bytes(bytecode)
    
    def get_disassembly(self) -> str:
        """Get human-readable disassembly for debugging."""
        lines = []
        for i, instr in enumerate(self.instructions):
            addr = i * 4
            lines.append(f"{addr:04X}: {instr}")
        return "\n".join(lines)
    
    def get_c_array(self, name: str = None) -> str:
        """Generate C array declaration for bytecode."""
        if name is None:
            name = _rnd_name()
        
        bytecode = self.finalize()
        hex_values = ", ".join(f"0x{b:02X}" for b in bytecode)
        key_vals = ", ".join(f"0x{k:08X}" for k in self.tea_key)
        
        return f"""
static const uint8_t {name}[] = {{
    {hex_values}
}};
static const size_t {name}_len = {len(bytecode)};
static const uint32_t {name}_tea_key[4] = {{ {key_vals} }};
static const uint64_t {name}_tea_nonce = 0x{self.tea_nonce:016X}ULL;
"""


class BytecodeBuilder:
    """
    Higher-level builder for constructing bytecode from C-like constructs.
    """
    
    def __init__(self):
        self.emitter = BytecodeEmitter()
        self.var_regs: Dict[str, int] = {}  # Variable name -> register
        self.next_reg = 0
    
    def alloc_reg(self, name: str = None) -> int:
        """Allocate a register for a variable."""
        if name and name in self.var_regs:
            return self.var_regs[name]
        
        if self.next_reg >= 8:
            raise RuntimeError("Out of registers")
        
        reg = self.next_reg
        self.next_reg += 1
        
        if name:
            self.var_regs[name] = reg
        
        return reg
    
    def free_reg(self, reg: int):
        """Free a register (for future optimization)."""
        # Simple: just mark as available if it's the last one
        if reg == self.next_reg - 1:
            self.next_reg -= 1
    
    def build_if(self, cond_reg: int, true_block, false_block=None):
        """Build if-else construct."""
        false_label = Label()
        end_label = Label()
        
        # Compare condition with zero
        self.emitter.emit_cmp(cond_reg, cond_reg)  # Sets zero if reg is 0
        self.emitter.emit_jz(false_label)
        
        # True block
        true_block(self)
        if false_block:
            self.emitter.emit_jmp(end_label)
        
        # False block
        self.emitter.labels[false_label.name] = false_label
        false_label.address = len(self.emitter.instructions) * 4
        
        if false_block:
            false_block(self)
            self.emitter.labels[end_label.name] = end_label
            end_label.address = len(self.emitter.instructions) * 4
    
    def build_while(self, cond_fn, body_fn):
        """Build while loop construct."""
        start_label = self.emitter.label()
        end_label = Label()
        
        # Condition check
        cond_reg = cond_fn(self)
        self.emitter.emit_cmp(cond_reg, cond_reg)
        self.emitter.emit_jz(end_label)
        
        # Body
        body_fn(self)
        
        # Loop back
        self.emitter.emit_jmp(start_label)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
    
    def finalize(self) -> bytes:
        """Finalize and return bytecode."""
        self.emitter.emit_halt()
        return self.emitter.finalize()
