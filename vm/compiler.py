"""
VM Compiler - AST-based compilation of C/C++ to VM bytecode
"""

import random
import string
import re
import ast
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from .opcodes import Op, Reg, Instruction, OpcodeShuffler, VM_REG_COUNT
from .emitter import BytecodeEmitter, Label
from .struct_analyzer import StructLayoutAnalyzer


def _rnd_name():
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


_QUAL_RE = re.compile(r'\b(const|volatile|restrict|__ptr64|__unaligned)\b')


def _normalize_type(type_str: str) -> str:
    if not type_str:
        return ""
    t = type_str.replace("struct ", "").replace("class ", "")
    t = _QUAL_RE.sub("", t)
    return " ".join(t.replace("  ", " ").split()).strip()


def _parse_type(type_str: str) -> Tuple[str, int, List[int]]:
    t = _normalize_type(type_str)
    dims = [int(m) for m in re.findall(r'\[(\d+)\]', t)]
    t = re.sub(r'\s*\[\d+\]', '', t).strip()
    ptr_depth = t.count('*')
    base = t.replace('*', '').strip()
    return base, ptr_depth, dims


def _decode_string_literal(lit: str) -> bytes:
    if not lit:
        return b""
    s = lit
    # Strip common C++ string literal prefixes while preserving quotes.
    if s.startswith('u8"'):
        s = s[2:]
    elif s.startswith(('u"', 'U"', 'L"')):
        s = s[1:]
    try:
        val = ast.literal_eval(s)
    except Exception:
        if s.startswith('"') and s.endswith('"'):
            val = s[1:-1]
        else:
            val = s
    if isinstance(val, bytes):
        return val
    if isinstance(val, str):
        return val.encode('utf-8', errors='replace')
    return str(val).encode('utf-8', errors='replace')


class CompilerContext:
    """Maintains state during compilation with type tracking for struct member access."""
    
    def __init__(self, global_plt_indices: Dict[str, int] = None, struct_layouts: Dict = None):
        self.var_regs: Dict[str, int] = {}  # variable name -> register
        self.next_reg = 1  # Reserve R0 for call/return conventions
        self.max_regs = VM_REG_COUNT
        self.labels: Dict[str, Label] = {}
        self.loop_stack: List[Tuple[Label, Label]] = []  # (continue_label, break_label)
        self.break_stack: List[Label] = []  # break targets for switch
        self.heap_allocs: List[int] = []  # registers holding heap allocations
        self.addr_vars: Dict[str, int] = {}  # local scalars with address storage
        # External function table for FCALL
        self.func_table: List[str] = []  # List of function names (for local tracking)
        self.func_indices: Dict[str, int] = {}  # name -> index
        # PLT/GOT: Use global indices if provided
        self.global_plt_indices = global_plt_indices or {}
        
        # Type tracking for struct member access
        self.var_types: Dict[str, str] = {}  # variable name -> type string
        self.struct_layouts = struct_layouts or {}  # struct name -> StructLayout
        self.global_vars: Dict[str, str] = {}  # global var name -> type string
        # String literal tracking for VM global injection
        self.string_literals: Dict[str, Tuple[str, str]] = {}  # literal -> (name, type)
        self.string_literal_defs: Dict[str, str] = {}  # name -> literal text
    
    def set_var_type(self, name: str, type_str: str):
        """Record the type of a variable."""
        self.var_types[name] = type_str
    
    def get_var_type(self, name: str) -> str:
        """Get the type of a variable, or empty string if unknown."""
        return self.var_types.get(name, "")
    
    def get_member_offset(self, struct_type: str, member_name: str) -> int:
        """Get the offset of a struct member. Returns 0 if unknown."""
        # Clean up type string (remove 'struct ', '*', etc.)
        clean_type = struct_type.replace('struct ', '').replace('*', '').strip()
        
        if clean_type in self.struct_layouts:
            offset = self.struct_layouts[clean_type].get_field_offset(member_name)
            if offset is not None:
                return offset
        
        # Fallback: return 0 (this will cause issues, but allows compilation)
        return 0

    def get_member_size(self, struct_type: str, member_name: str) -> int:
        """Get the size of a struct member. Returns 8 if unknown."""
        clean_type = struct_type.replace('struct ', '').replace('*', '').strip()
        if clean_type in self.struct_layouts:
            size = self.struct_layouts[clean_type].get_field_size(member_name)
            if size is not None:
                return size
        return 8

    def get_type_size(self, type_str: str) -> int:
        """Get size in bytes for a type string."""
        base, ptr_depth, dims = _parse_type(type_str)
        if ptr_depth > 0:
            return 8
        if base in self.struct_layouts:
            base_size = self.struct_layouts[base].total_size
        else:
            base_size = StructLayoutAnalyzer.TYPE_SIZES.get(base, 8)
        if dims:
            total = base_size
            for d in dims:
                total *= d
            return total
        return base_size

    def get_element_size(self, type_str: str) -> int:
        """Get element size for array or pointer types."""
        base, ptr_depth, dims = _parse_type(type_str)
        if dims:
            base_size = self.get_type_size(base)
            if len(dims) > 1:
                for d in dims[1:]:
                    base_size *= d
            return base_size
        if ptr_depth > 0:
            if ptr_depth > 1:
                return 8
            return self.get_type_size(base)
        return self.get_type_size(type_str)
    
    def register_func(self, name: str) -> int:
        """Register an external function and return its index."""
        # PLT/GOT: If global PLT mapping exists, use global index
        if self.global_plt_indices and name in self.global_plt_indices:
            # Also track in local list for reference
            if name not in self.func_indices:
                self.func_table.append(name)
                self.func_indices[name] = self.global_plt_indices[name]
            return self.global_plt_indices[name]
        
        # Fallback: local index assignment (original behavior)
        if name not in self.func_indices:
            idx = len(self.func_table)
            self.func_table.append(name)
            self.func_indices[name] = idx
        return self.func_indices[name]

    def register_global(self, name: str, type_str: str) -> str:
        """Record global variable usage and return helper function name."""
        if name not in self.global_vars:
            self.global_vars[name] = type_str
        safe = ''.join(c if c.isalnum() else '_' for c in name)
        return f"_vm_gaddr_{safe}"

    def register_string_literal(self, literal: str) -> Tuple[str, str]:
        """Register a string literal and return (name, type_str)."""
        if literal in self.string_literals:
            return self.string_literals[literal]
        digest = hashlib.sha256(literal.encode('utf-8', errors='replace')).hexdigest()
        name = f"_vm_str_{digest[:16]}"
        if name in self.string_literal_defs and self.string_literal_defs[name] != literal:
            name = f"{name}_{digest[16:20]}"
        size = len(_decode_string_literal(literal)) + 1
        type_str = f"const char [{size}]"
        self.string_literals[literal] = (name, type_str)
        self.string_literal_defs[name] = literal
        return name, type_str
    
    def alloc_reg(self, name: str = None) -> int:
        """Allocate a register."""
        if name and name in self.var_regs:
            return self.var_regs[name]

        if self.next_reg >= self.max_regs:
            # Fallback to the last register to keep compilation moving.
            reg = self.max_regs - 1
        else:
            reg = self.next_reg
            self.next_reg += 1
        
        if name:
            self.var_regs[name] = reg
        
        return reg
    
    def get_reg(self, name: str) -> Optional[int]:
        """Get register for variable, or None if not found."""
        return self.var_regs.get(name)
    
    def free_reg(self, reg: int):
        """Mark register as free."""
        if reg == self.next_reg - 1:
            self.next_reg -= 1
    
    def push_loop(self, cont: Label, brk: Label):
        self.loop_stack.append((cont, brk))
    
    def pop_loop(self):
        if self.loop_stack:
            self.loop_stack.pop()
    
    def current_loop(self) -> Optional[Tuple[Label, Label]]:
        return self.loop_stack[-1] if self.loop_stack else None

    def push_break(self, brk: Label):
        self.break_stack.append(brk)

    def pop_break(self):
        if self.break_stack:
            self.break_stack.pop()

    def current_break(self) -> Optional[Label]:
        return self.break_stack[-1] if self.break_stack else None

    def register_heap_alloc(self, reg: int):
        if reg not in self.heap_allocs:
            self.heap_allocs.append(reg)


class ASTCompiler:
    """
    Compiles Clang AST nodes to VM bytecode.
    """
    
    def __init__(self, shuffler: OpcodeShuffler = None):
        self.shuffler = shuffler or OpcodeShuffler()
        self.emitter: Optional[BytecodeEmitter] = None
        self.ctx: Optional[CompilerContext] = None
        self.source_code: str = ""

    def _unwrap_casts(self, node: Dict) -> Dict:
        """Strip common cast wrappers to reach the underlying expression."""
        cur = node
        while cur and cur.get("kind") in ("ImplicitCastExpr", "CStyleCastExpr", "ParenExpr",
                                          "CXXStaticCastExpr", "CXXReinterpretCastExpr",
                                          "CXXConstCastExpr", "CXXFunctionalCastExpr",
                                          "ConstantExpr"):
            inner = cur.get("inner", [])
            if not inner:
                break
            cur = inner[0]
        return cur

    def _addr_of_local_scalar(self, node: Dict) -> Optional[Tuple[str, str]]:
        """Detect &local_scalar and return (name, type_str) or None."""
        cur = self._unwrap_casts(node)
        if not cur or cur.get("kind") != "UnaryOperator" or cur.get("opcode") != "&":
            return None
        inner = cur.get("inner", [])
        if not inner:
            return None
        target = self._unwrap_casts(inner[0])
        if not target or target.get("kind") != "DeclRefExpr":
            return None
        name = target.get("referencedDecl", {}).get("name", "")
        if not name:
            return None
        if self.ctx.get_reg(name) is None:
            return None
        t = self.ctx.get_var_type(name) or self._get_node_type(target)
        base, ptr_depth, dims = _parse_type(t)
        if ptr_depth == 0 and not dims:
            return name, t
        return None

    def _ensure_addr_var(self, name: str, type_str: str) -> int:
        """Ensure addressable storage for a local scalar and return its pointer reg."""
        if name in self.ctx.addr_vars:
            return self.ctx.addr_vars[name]
        addr_reg = self.ctx.alloc_reg()
        size = self.ctx.get_type_size(type_str)
        size_reg = self.ctx.alloc_reg()
        self._emit_const(size_reg, size)
        if size_reg != 0:
            self.emitter.emit_mov(0, size_reg)
        self.emitter.emit_alloc()
        if addr_reg != 0:
            self.emitter.emit_mov(addr_reg, 0)
        self.ctx.free_reg(size_reg)
        self.ctx.register_heap_alloc(addr_reg)
        self.ctx.addr_vars[name] = addr_reg
        return addr_reg
    
    def compile_function(self, func_node: Dict, source_code: str, global_plt_indices: Dict[str, int] = None, struct_layouts: Dict = None) -> Tuple[bytes, str, List[str], Dict[str, str]]:
        """
        Compile a function declaration AST node to VM bytecode.
        Returns (bytecode, c_array_code, func_table, string_literals).
        
        Args:
            global_plt_indices: If provided, FCALL will use global PLT indices instead of local
            struct_layouts: Dict of struct name -> StructLayout for member offset lookups
        """
        self.emitter = BytecodeEmitter(self.shuffler)
        self.ctx = CompilerContext(global_plt_indices, struct_layouts)
        self.source_code = source_code
        
        # Get function name and sanitize for C identifier
        func_name = func_node.get("name", "unknown")
        # Sanitize: replace non-alphanumeric chars with underscores
        safe_name = ''.join(c if c.isalnum() else '_' for c in func_name)
        # Add random suffix to ensure uniqueness (for overloaded functions like operator<<)
        unique_suffix = ''.join(random.choices(string.hexdigits[:16], k=4))
        safe_name = f"{safe_name}_{unique_suffix}"
        
        # Process parameters - allocate registers AND track types
        param_regs: List[Tuple[int, int]] = []
        for child in func_node.get("inner", []):
            if child.get("kind") == "ParmVarDecl":
                param_name = child.get("name")
                param_type = child.get("type", {}).get("qualType", "")
                if param_name:
                    reg = self.ctx.alloc_reg(param_name)
                    self.ctx.set_var_type(param_name, param_type)
                    param_regs.append((len(param_regs), reg))
        
        # Find and compile the body (CompoundStmt in inner array)
        body = None
        for child in func_node.get("inner", []):
            if child.get("kind") == "CompoundStmt":
                body = child
                break
        
        if body:
            # Move incoming args into assigned registers (R0-R7 -> var regs)
            # Reverse order avoids clobbering later args when regs overlap.
            for idx, reg in reversed(param_regs):
                if idx < 8 and reg != idx:
                    self.emitter.emit_mov(reg, idx)
            self.compile_stmt(body)
        
        if self.ctx.heap_allocs:
            for reg in self.ctx.heap_allocs:
                if reg != 0:
                    self.emitter.emit_mov(0, reg)
                self.emitter.emit_free()

        # Ensure function returns
        self.emitter.emit_halt()
        
        # Generate output
        bytecode = self.emitter.finalize()
        c_array = self.emitter.get_c_array(f"_vm_{safe_name}")
        func_table = self.ctx.func_table  # List of external function names called
        string_literals = dict(self.ctx.string_literal_defs)
        
        return bytecode, c_array, func_table, string_literals
    
    def compile_stmt(self, node: Dict):
        """Compile a statement node."""
        kind = node.get("kind", "")
        
        if kind == "CompoundStmt":
            for child in node.get("inner", []):
                self.compile_stmt(child)
        
        elif kind == "DeclStmt":
            for decl in node.get("inner", []):
                self.compile_decl(decl)
        
        elif kind == "ReturnStmt":
            inner = node.get("inner", [])
            if inner:
                # Compile return expression into R0
                self.compile_expr(inner[0], 0)
            if self.ctx.heap_allocs:
                saved = None
                if inner:
                    saved = self.ctx.alloc_reg()
                    self.emitter.emit_mov(saved, 0)
                for reg in self.ctx.heap_allocs:
                    if reg != 0:
                        self.emitter.emit_mov(0, reg)
                    self.emitter.emit_free()
                if saved is not None:
                    self.emitter.emit_mov(0, saved)
                    self.ctx.free_reg(saved)
            # Top-level VM-protected functions are not called via CALL,
            # so early returns should halt execution instead of RET.
            self.emitter.emit_halt()
        
        elif kind == "IfStmt":
            self.compile_if(node)
        
        elif kind == "WhileStmt":
            self.compile_while(node)
        
        elif kind == "ForStmt":
            self.compile_for(node)

        elif kind == "SwitchStmt":
            self.compile_switch(node)
        
        elif kind == "BreakStmt":
            loop = self.ctx.current_loop()
            if loop:
                self.emitter.emit_jmp(loop[1])  # break label
            else:
                brk = self.ctx.current_break()
                if brk:
                    self.emitter.emit_jmp(brk)
        
        elif kind == "ContinueStmt":
            loop = self.ctx.current_loop()
            if loop:
                self.emitter.emit_jmp(loop[0])  # continue label
        
        elif kind in ("BinaryOperator", "CompoundAssignOperator"):
            # Expression statement
            self.compile_expr(node, self.ctx.alloc_reg())
        
        elif kind == "UnaryOperator":
            self.compile_expr(node, self.ctx.alloc_reg())
        
        elif kind == "CallExpr":
            self.compile_call(node, self.ctx.alloc_reg())
        
        elif kind == "NullStmt":
            pass  # Nothing to do
        
        else:
            # Try to compile as expression
            try:
                self.compile_expr(node, self.ctx.alloc_reg())
            except:
                pass  # Ignore unknown statement types
    
    def compile_decl(self, node: Dict):
        """Compile a declaration."""
        kind = node.get("kind", "")
        
        if kind == "VarDecl":
            name = node.get("name")
            if name:
                type_str = node.get("type", {}).get("qualType", "")
                base, ptr_depth, dims = _parse_type(type_str)
                reg = self.ctx.alloc_reg(name)
                self.ctx.set_var_type(name, type_str)
                
                # Check for initializer
                inner = node.get("inner", [])
                if dims:
                    total_elems = 1
                    for d in dims:
                        total_elems *= d
                    elem_size = self.ctx.get_type_size(base)
                    total_size = total_elems * elem_size
                    
                    size_reg = self.ctx.alloc_reg()
                    self._emit_const(size_reg, total_size)
                    if size_reg != 0:
                        self.emitter.emit_mov(0, size_reg)
                    self.emitter.emit_alloc()
                    if reg != 0:
                        self.emitter.emit_mov(reg, 0)
                    self.ctx.free_reg(size_reg)
                    self.ctx.register_heap_alloc(reg)
                    
                    if inner:
                        init = inner[0]
                        values = self._flatten_init_list(init)
                        for idx, expr in enumerate(values):
                            addr_reg = self.ctx.alloc_reg()
                            self.emitter.emit_mov(addr_reg, reg)
                            if idx:
                                off_reg = self.ctx.alloc_reg()
                                self._emit_const(off_reg, idx * elem_size)
                                self.emitter.emit_add(addr_reg, addr_reg, off_reg)
                                self.ctx.free_reg(off_reg)
                            val_reg = self.ctx.alloc_reg()
                            self.compile_expr(expr, val_reg)
                            self._emit_store_by_size(addr_reg, val_reg, elem_size)
                            self.ctx.free_reg(val_reg)
                            self.ctx.free_reg(addr_reg)
                else:
                    if inner:
                        self.compile_expr(inner[0], reg)
                    else:
                        # Initialize to zero
                        self._emit_const(reg, 0)

    def _flatten_init_list(self, node: Dict) -> List[Dict]:
        """Flatten an InitListExpr into a list of element expressions."""
        if not node:
            return []
        if node.get("kind") == "InitListExpr":
            values: List[Dict] = []
            for child in node.get("inner", []):
                values.extend(self._flatten_init_list(child))
            return values
        return [node]

    def _emit_const(self, dest_reg: int, value: int):
        """Emit instructions to load a full-width constant into dest_reg."""
        value &= 0xFFFFFFFFFFFFFFFF
        if value == 0:
            self.emitter.emit_movi(dest_reg, 0)
            return
        
        parts = []
        for shift in range(0, 64, 16):
            part = (value >> shift) & 0xFFFF
            if part:
                parts.append((shift, part))
        
        self.emitter.emit_movi(dest_reg, 0)
        for shift, part in parts:
            tmp = self.ctx.alloc_reg()
            self.emitter.emit_movi(tmp, part)
            if shift:
                shift_reg = self.ctx.alloc_reg()
                self.emitter.emit_movi(shift_reg, shift)
                self.emitter.emit_shl(tmp, tmp, shift_reg)
                self.ctx.free_reg(shift_reg)
            self.emitter.emit_or(dest_reg, dest_reg, tmp)
            self.ctx.free_reg(tmp)

    def _emit_global_addr(self, name: str, type_str: str, dest_reg: int) -> int:
        """Emit code to load the address of a global variable into dest_reg."""
        helper_name = self.ctx.register_global(name, type_str)
        func_idx = self.ctx.register_func(helper_name)
        # Save caller registers (R1-R7); R0 is used for return
        for r in range(1, 8):
            self.emitter.emit_push(r)
        self.emitter.emit_fcall(func_idx)
        for r in range(7, 0, -1):
            self.emitter.emit_pop(r)
        if dest_reg != 0:
            self.emitter.emit_mov(dest_reg, 0)
        return dest_reg

    def _get_node_type(self, node: Dict) -> str:
        if not node:
            return ""
        kind = node.get("kind", "")
        if kind == "DeclRefExpr":
            ref = node.get("referencedDecl", {})
            t = ref.get("type", {}).get("qualType", "")
            if t:
                return t
        t = node.get("type", {}).get("qualType", "")
        if t:
            return t
        if kind in ("ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "CXXStaticCastExpr",
                    "CXXReinterpretCastExpr", "CXXConstCastExpr", "CXXFunctionalCastExpr",
                    "ConstantExpr"):
            inner = node.get("inner", [])
            if inner:
                return self._get_node_type(inner[0])
        return ""

    def _emit_load_by_size(self, dest_reg: int, addr_reg: int, size: int):
        if size <= 1:
            self.emitter.emit_load8(dest_reg, addr_reg)
            return
        if size <= 2:
            self.emitter.emit_load16(dest_reg, addr_reg)
            return
        if size <= 4:
            low = self.ctx.alloc_reg()
            high = self.ctx.alloc_reg()
            addr_high = self.ctx.alloc_reg()
            
            self.emitter.emit_mov(addr_high, addr_reg)
            self.emitter.emit_addi(addr_high, addr_high, 2)
            self.emitter.emit_load16(low, addr_reg)
            self.emitter.emit_load16(high, addr_high)
            
            shift_reg = self.ctx.alloc_reg()
            self._emit_const(shift_reg, 16)
            self.emitter.emit_shl(high, high, shift_reg)
            self.ctx.free_reg(shift_reg)
            
            self.emitter.emit_or(dest_reg, low, high)
            
            self.ctx.free_reg(addr_high)
            self.ctx.free_reg(high)
            self.ctx.free_reg(low)
            return
        self.emitter.emit_load(dest_reg, addr_reg)

    def _emit_store_by_size(self, addr_reg: int, src_reg: int, size: int):
        if size <= 1:
            self.emitter.emit_store8(addr_reg, src_reg)
            return
        if size <= 2:
            self.emitter.emit_store16(addr_reg, src_reg)
            return
        if size <= 4:
            low = self.ctx.alloc_reg()
            high = self.ctx.alloc_reg()
            addr_high = self.ctx.alloc_reg()
            
            self.emitter.emit_mov(addr_high, addr_reg)
            self.emitter.emit_addi(addr_high, addr_high, 2)
            
            mask = self.ctx.alloc_reg()
            self._emit_const(mask, 0xFFFF)
            self.emitter.emit_mov(low, src_reg)
            self.emitter.emit_and(low, low, mask)
            self.emitter.emit_store16(addr_reg, low)
            
            self.emitter.emit_mov(high, src_reg)
            shift_reg = self.ctx.alloc_reg()
            self._emit_const(shift_reg, 16)
            self.emitter.emit_shr(high, high, shift_reg)
            self.emitter.emit_store16(addr_high, high)
            
            self.ctx.free_reg(shift_reg)
            self.ctx.free_reg(mask)
            self.ctx.free_reg(addr_high)
            self.ctx.free_reg(high)
            self.ctx.free_reg(low)
            return
        self.emitter.emit_store(addr_reg, src_reg)

    def _compile_lvalue_address(self, node: Dict, dest_reg: int) -> int:
        """Compute address of an lvalue into dest_reg; returns size in bytes or 0 if unknown."""
        if not node:
            return 0
        kind = node.get("kind", "")
        
        if kind in ("ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "CXXStaticCastExpr",
                    "CXXReinterpretCastExpr", "CXXConstCastExpr", "CXXFunctionalCastExpr"):
            inner = node.get("inner", [])
            if inner:
                return self._compile_lvalue_address(inner[0], dest_reg)
            return 0
        
        if kind == "DeclRefExpr":
            name = node.get("referencedDecl", {}).get("name", "")
            reg = self.ctx.get_reg(name)
            if reg is None:
                t = self._get_node_type(node)
                if not name:
                    return 0
                # Global variable: return its address for lvalue operations
                self._emit_global_addr(name, t, dest_reg)
                return self.ctx.get_type_size(t)
            t = self.ctx.get_var_type(name) or self._get_node_type(node)
            base, ptr_depth, dims = _parse_type(t)
            if ptr_depth == 0 and not dims:
                return 0
            if reg != dest_reg:
                self.emitter.emit_mov(dest_reg, reg)
            return self.ctx.get_element_size(t)
        
        if kind == "UnaryOperator" and node.get("opcode") == "*":
            inner = node.get("inner", [])
            if inner:
                self.compile_expr(inner[0], dest_reg)
                t = self._get_node_type(node)
                return self.ctx.get_type_size(t)
            return 0
        
        if kind == "MemberExpr":
            inner = node.get("inner", [])
            if not inner:
                return 0
            base_node = inner[0]
            base_reg = self.ctx.alloc_reg()
            is_arrow = node.get("isArrow", False)
            if is_arrow:
                self.compile_expr(base_node, base_reg)
            else:
                base_size = self._compile_lvalue_address(base_node, base_reg)
                if base_size == 0:
                    self.compile_expr(base_node, base_reg)
            
            member_name = node.get("name", "")
            base_type = self._get_node_type(base_node)
            offset = self.ctx.get_member_offset(base_type, member_name)
            if offset:
                off_reg = self.ctx.alloc_reg()
                self._emit_const(off_reg, offset)
                self.emitter.emit_add(base_reg, base_reg, off_reg)
                self.ctx.free_reg(off_reg)
            
            if base_reg != dest_reg:
                self.emitter.emit_mov(dest_reg, base_reg)
            
            size = self.ctx.get_member_size(base_type, member_name)
            self.ctx.free_reg(base_reg)
            return size
        
        if kind == "ArraySubscriptExpr":
            inner = node.get("inner", [])
            if len(inner) < 2:
                return 0
            base_node, idx_node = inner[0], inner[1]
            
            base_reg = self.ctx.alloc_reg()
            # Handle array-to-pointer decay for array lvalues (e.g., struct member arrays).
            force_array = False
            base_node_for_type = base_node
            if base_node.get("kind") in ("ImplicitCastExpr", "CStyleCastExpr"):
                if base_node.get("castKind") == "ArrayToPointerDecay":
                    inner_nodes = base_node.get("inner", [])
                    if inner_nodes:
                        base_node_for_type = inner_nodes[0]
                        force_array = True
            base_type = self._get_node_type(base_node_for_type)
            base_base, base_ptr_depth, base_dims = _parse_type(base_type)
            if not force_array and base_ptr_depth > 0 and not base_dims:
                # Pointer expression: use the pointer value, not address-of member.
                self.compile_expr(base_node, base_reg)
            else:
                base_size = self._compile_lvalue_address(base_node_for_type, base_reg)
                if base_size == 0:
                    self.compile_expr(base_node_for_type, base_reg)
            
            idx_reg = self.ctx.alloc_reg()
            self.compile_expr(idx_node, idx_reg)
            
            elem_size = self.ctx.get_element_size(base_type)
            if elem_size > 1:
                size_reg = self.ctx.alloc_reg()
                self._emit_const(size_reg, elem_size)
                self.emitter.emit_mul(idx_reg, idx_reg, size_reg)
                self.ctx.free_reg(size_reg)
            
            self.emitter.emit_add(base_reg, base_reg, idx_reg)
            if base_reg != dest_reg:
                self.emitter.emit_mov(dest_reg, base_reg)
            
            self.ctx.free_reg(idx_reg)
            self.ctx.free_reg(base_reg)
            return self.ctx.get_type_size(self._get_node_type(node))
        
        return 0
    
    def compile_expr(self, node: Dict, dest_reg: int) -> int:
        """
        Compile an expression node.
        Result goes into dest_reg.
        Returns the register containing the result.
        """
        kind = node.get("kind", "")
        
        if kind == "IntegerLiteral":
            value = int(node.get("value", "0"))
            self._emit_const(dest_reg, value)
            return dest_reg
        
        elif kind == "FloatingLiteral":
            # Convert to int (simplified)
            value = int(float(node.get("value", "0")))
            self._emit_const(dest_reg, value)
            return dest_reg
        
        elif kind == "CXXBoolLiteralExpr":
            # Boolean literals: true/false
            value = 1 if node.get("value", False) else 0
            self._emit_const(dest_reg, value)
            return dest_reg
        
        elif kind in ("CXXNullPtrLiteralExpr", "GNUNullExpr"):
            # NULL/nullptr literal
            self._emit_const(dest_reg, 0)
            return dest_reg
        
        elif kind == "DeclRefExpr":
            # Reference to a variable
            ref = node.get("referencedDecl", {})
            name = ref.get("name", "")
            
            src_reg = self.ctx.get_reg(name)
            if src_reg is not None:
                if src_reg != dest_reg:
                    self.emitter.emit_mov(dest_reg, src_reg)
                return dest_reg
            else:
                # Global variable: load address via helper, then load value as needed
                t = self._get_node_type(node)
                base, ptr_depth, dims = _parse_type(t)
                if name:
                    self._emit_global_addr(name, t, dest_reg)
                    # Arrays decay to pointer; return address directly.
                    if dims:
                        return dest_reg
                    # Load scalar/pointer value.
                    size = self.ctx.get_type_size(t)
                    self._emit_load_by_size(dest_reg, dest_reg, size)
                    return dest_reg
                # Fallback: unknown, return 0
                self._emit_const(dest_reg, 0)
                return dest_reg
        
        elif kind in ("ImplicitCastExpr", "CStyleCastExpr", "CXXStaticCastExpr", 
                      "CXXReinterpretCastExpr", "CXXConstCastExpr", "CXXFunctionalCastExpr",
                      "ConstantExpr"):
            # Pass through to inner expression (casts)
            inner = node.get("inner", [])
            if inner:
                return self.compile_expr(inner[0], dest_reg)
            return dest_reg
        
        elif kind == "ParenExpr":
            inner = node.get("inner", [])
            if inner:
                return self.compile_expr(inner[0], dest_reg)
            return dest_reg
        
        elif kind == "MemberExpr":
            # Struct member access: ptr->member or obj.member
            return self.compile_member_expr(node, dest_reg)
        
        elif kind == "BinaryOperator":
            return self.compile_binary_op(node, dest_reg)
        
        elif kind == "CompoundAssignOperator":
            return self.compile_compound_assign(node, dest_reg)
        
        elif kind == "UnaryOperator":
            return self.compile_unary_op(node, dest_reg)
        
        elif kind == "CallExpr":
            return self.compile_call(node, dest_reg)
        
        elif kind == "CXXMemberCallExpr":
            # C++ member function call - treat similar to CallExpr
            return self.compile_call(node, dest_reg)
        
        elif kind == "ConditionalOperator":
            return self.compile_ternary(node, dest_reg)
        
        elif kind == "ArraySubscriptExpr":
            return self.compile_array_access(node, dest_reg)
        
        elif kind == "SizeOfPackExpr" or kind == "UnaryExprOrTypeTraitExpr":
            # sizeof/alignof - compute from type info when possible
            size = 8
            if kind == "UnaryExprOrTypeTraitExpr" and node.get("name") == "sizeof":
                arg_type = node.get("argType", {}).get("qualType", "")
                if arg_type:
                    size = self.ctx.get_type_size(arg_type)
                else:
                    inner = node.get("inner", [])
                    if inner:
                        size = self.ctx.get_type_size(self._get_node_type(inner[0]))
            self._emit_const(dest_reg, size)
            return dest_reg
        
        elif kind == "StringLiteral":
            literal = node.get("value", "")
            name, type_str = self.ctx.register_string_literal(literal)
            self._emit_global_addr(name, type_str, dest_reg)
            return dest_reg
        
        elif kind == "InitListExpr":
            # Initializer list - compile first element if any
            inner = node.get("inner", [])
            if inner:
                return self.compile_expr(inner[0], dest_reg)
            self._emit_const(dest_reg, 0)
            return dest_reg
        
        return dest_reg
    
    def compile_member_expr(self, node: Dict, dest_reg: int) -> int:
        """
        Compile struct member access (ptr->member or obj.member).
        
        For ptr->member, generates:
            1. Compile base expression (ptr) to base_reg
            2. MOVI offset_reg, member_offset
            3. ADD addr_reg, base_reg, offset_reg
            4. LOAD dest_reg, addr_reg
        """
        addr_reg = self.ctx.alloc_reg()
        size = self._compile_lvalue_address(node, addr_reg)
        t = self._get_node_type(node)
        base, ptr_depth, dims = _parse_type(t)
        if dims:
            # Array member decays to pointer; return address directly.
            if addr_reg != dest_reg:
                self.emitter.emit_mov(dest_reg, addr_reg)
            self.ctx.free_reg(addr_reg)
            return dest_reg
        if size > 0:
            self._emit_load_by_size(dest_reg, addr_reg, size)
        else:
            self._emit_const(dest_reg, 0)
        self.ctx.free_reg(addr_reg)
        return dest_reg
    
    def compile_binary_op(self, node: Dict, dest_reg: int) -> int:
        """Compile binary operator."""
        opcode = node.get("opcode", "")
        inner = node.get("inner", [])
        
        if len(inner) < 2:
            return dest_reg
        
        left_node, right_node = inner[0], inner[1]
        
        # Assignment
        if opcode == "=":
            # Left side should be assignable (DeclRefExpr)
            left_ref = self._get_decl_ref(left_node)
            if left_ref:
                left_reg = self.ctx.get_reg(left_ref)
                if left_reg is not None:
                    self.compile_expr(right_node, left_reg)
                    if left_reg != dest_reg:
                        self.emitter.emit_mov(dest_reg, left_reg)
                    return dest_reg
            addr_reg = self.ctx.alloc_reg()
            size = self._compile_lvalue_address(left_node, addr_reg)
            if size:
                val_reg = self.ctx.alloc_reg()
                self.compile_expr(right_node, val_reg)
                self._emit_store_by_size(addr_reg, val_reg, size)
                if dest_reg != val_reg:
                    self.emitter.emit_mov(dest_reg, val_reg)
                self.ctx.free_reg(val_reg)
            self.ctx.free_reg(addr_reg)
            return dest_reg
        
        # Arithmetic and bitwise operators
        op_map = {
            '+': Op.ADD, '-': Op.SUB, '*': Op.MUL, '/': Op.DIV, '%': Op.MOD,
            '&': Op.AND, '|': Op.OR, '^': Op.XOR,
            '<<': Op.SHL, '>>': Op.SHR,
        }
        
        if opcode in op_map:
            left_reg = self.ctx.alloc_reg()
            right_reg = self.ctx.alloc_reg()
            
            self.compile_expr(left_node, left_reg)
            self.compile_expr(right_node, right_reg)
            
            self.emitter.emit(Instruction(op_map[opcode], dst=dest_reg, src1=left_reg, src2=right_reg))
            
            self.ctx.free_reg(right_reg)
            self.ctx.free_reg(left_reg)
            return dest_reg
        
        # Comparison operators
        cmp_jump = {
            '==': Op.JZ,
            '!=': Op.JNZ,
            '<': Op.JL,
            '<=': Op.JLE,
            '>': Op.JG,
            '>=': Op.JGE,
        }
        
        if opcode in cmp_jump:
            left_reg = self.ctx.alloc_reg()
            right_reg = self.ctx.alloc_reg()
            
            self.compile_expr(left_node, left_reg)
            self.compile_expr(right_node, right_reg)
            
            self.emitter.emit_cmp(left_reg, right_reg)
            self._emit_const(dest_reg, 0)
            
            true_label = Label()
            end_label = Label()
            self.emitter._emit_jump(cmp_jump[opcode], true_label)
            self.emitter._emit_jump(Op.JMP, end_label)
            
            self.emitter.labels[true_label.name] = true_label
            true_label.address = len(self.emitter.instructions) * 4
            self._emit_const(dest_reg, 1)
            
            self.emitter.labels[end_label.name] = end_label
            end_label.address = len(self.emitter.instructions) * 4
            
            self.ctx.free_reg(right_reg)
            self.ctx.free_reg(left_reg)
            return dest_reg
        
        # Logical operators
        if opcode == "&&":
            return self.compile_logical_and(left_node, right_node, dest_reg)
        elif opcode == "||":
            return self.compile_logical_or(left_node, right_node, dest_reg)
        
        return dest_reg
    
    def compile_compound_assign(self, node: Dict, dest_reg: int) -> int:
        """Compile compound assignment (+=, -=, etc.)."""
        opcode = node.get("opcode", "")
        inner = node.get("inner", [])
        
        if len(inner) < 2:
            return dest_reg
        
        left_node, right_node = inner[0], inner[1]

        op_map = {
            '+=': Op.ADD, '-=': Op.SUB, '*=': Op.MUL, '/=': Op.DIV, '%=': Op.MOD,
            '&=': Op.AND, '|=': Op.OR, '^=': Op.XOR,
            '<<=': Op.SHL, '>>=': Op.SHR,
        }

        left_ref = self._get_decl_ref(left_node)
        if not left_ref:
            addr_reg = self.ctx.alloc_reg()
            size = self._compile_lvalue_address(left_node, addr_reg)
            if not size:
                self.ctx.free_reg(addr_reg)
                return dest_reg
            
            left_val = self.ctx.alloc_reg()
            self._emit_load_by_size(left_val, addr_reg, size)
            right_reg = self.ctx.alloc_reg()
            self.compile_expr(right_node, right_reg)
            
            if opcode in op_map:
                self.emitter.emit(Instruction(op_map[opcode], dst=left_val, src1=left_val, src2=right_reg))
                self._emit_store_by_size(addr_reg, left_val, size)
                if dest_reg != left_val:
                    self.emitter.emit_mov(dest_reg, left_val)
            
            self.ctx.free_reg(right_reg)
            self.ctx.free_reg(left_val)
            self.ctx.free_reg(addr_reg)
            return dest_reg
        
        left_reg = self.ctx.get_reg(left_ref)
        if left_reg is None:
            return dest_reg
        
        if opcode in op_map:
            right_reg = self.ctx.alloc_reg()
            self.compile_expr(right_node, right_reg)
            self.emitter.emit(Instruction(op_map[opcode], dst=left_reg, src1=left_reg, src2=right_reg))
            self.ctx.free_reg(right_reg)
            
            if left_reg != dest_reg:
                self.emitter.emit_mov(dest_reg, left_reg)
        
        return dest_reg
    
    def compile_unary_op(self, node: Dict, dest_reg: int) -> int:
        """Compile unary operator."""
        opcode = node.get("opcode", "")
        inner = node.get("inner", [])
        
        if not inner:
            return dest_reg
        
        operand = inner[0]
        
        if opcode == "-":
            self.compile_expr(operand, dest_reg)
            self.emitter.emit(Instruction(Op.NEG, dst=dest_reg, src1=dest_reg))
        elif opcode == "~":
            self.compile_expr(operand, dest_reg)
            self.emitter.emit_not(dest_reg, dest_reg)
        elif opcode == "!":
            self.compile_expr(operand, dest_reg)
            # !x: compare with 0, set result
            temp = self.ctx.alloc_reg()
            self._emit_const(temp, 0)
            self.emitter.emit_cmp(dest_reg, temp)
            self._emit_const(dest_reg, 0)
            
            true_label = Label()
            end_label = Label()
            self.emitter._emit_jump(Op.JZ, true_label)
            self.emitter._emit_jump(Op.JMP, end_label)
            
            self.emitter.labels[true_label.name] = true_label
            true_label.address = len(self.emitter.instructions) * 4
            self._emit_const(dest_reg, 1)
            
            self.emitter.labels[end_label.name] = end_label
            end_label.address = len(self.emitter.instructions) * 4
            
            self.ctx.free_reg(temp)
        elif opcode in ("++", "--"):
            is_prefix = node.get("isPostfix", False) == False
            op = Op.INC if opcode == "++" else Op.DEC
            
            ref = self._get_decl_ref(operand)
            if ref:
                reg = self.ctx.get_reg(ref)
                t = self.ctx.get_var_type(ref)
                base, ptr_depth, dims = _parse_type(t)
                if reg is not None and ptr_depth == 0 and not dims:
                    if is_prefix:
                        self.emitter.emit(Instruction(op, dst=reg))
                        if reg != dest_reg:
                            self.emitter.emit_mov(dest_reg, reg)
                    else:
                        if reg != dest_reg:
                            self.emitter.emit_mov(dest_reg, reg)
                        self.emitter.emit(Instruction(op, dst=reg))
                    return dest_reg
            
            addr_reg = self.ctx.alloc_reg()
            size = self._compile_lvalue_address(operand, addr_reg)
            if size == 0:
                self._emit_const(dest_reg, 0)
                self.ctx.free_reg(addr_reg)
                return dest_reg
            
            val_reg = self.ctx.alloc_reg()
            self._emit_load_by_size(val_reg, addr_reg, size)
            
            if is_prefix:
                self.emitter.emit(Instruction(op, dst=val_reg))
                self._emit_store_by_size(addr_reg, val_reg, size)
                if dest_reg != val_reg:
                    self.emitter.emit_mov(dest_reg, val_reg)
            else:
                if dest_reg != val_reg:
                    self.emitter.emit_mov(dest_reg, val_reg)
                    self.emitter.emit(Instruction(op, dst=val_reg))
                    self._emit_store_by_size(addr_reg, val_reg, size)
                else:
                    old_reg = self.ctx.alloc_reg()
                    self.emitter.emit_mov(old_reg, val_reg)
                    self.emitter.emit(Instruction(op, dst=val_reg))
                    self._emit_store_by_size(addr_reg, val_reg, size)
                    self.emitter.emit_mov(dest_reg, old_reg)
                    self.ctx.free_reg(old_reg)
            
            self.ctx.free_reg(val_reg)
            self.ctx.free_reg(addr_reg)
        elif opcode == "&":
            # Address-of operator - get pointer to variable
            size = self._compile_lvalue_address(operand, dest_reg)
            if size == 0:
                self._emit_const(dest_reg, 0)
        elif opcode == "*":
            # Dereference operator - load value from pointer
            self.compile_expr(operand, dest_reg)
            size = self.ctx.get_type_size(self._get_node_type(node))
            self._emit_load_by_size(dest_reg, dest_reg, size)
        
        return dest_reg
    
    def compile_call(self, node: Dict, dest_reg: int) -> int:
        """Compile function call."""
        inner = node.get("inner", [])
        if not inner:
            return dest_reg
        
        # First child is the function reference
        func_ref = inner[0]
        func_name = None
        
        if func_ref.get("kind") == "ImplicitCastExpr":
            cast_inner = func_ref.get("inner", [])
            if cast_inner and cast_inner[0].get("kind") == "DeclRefExpr":
                func_name = cast_inner[0].get("referencedDecl", {}).get("name")
        elif func_ref.get("kind") == "DeclRefExpr":
            func_name = func_ref.get("referencedDecl", {}).get("name")
        
        if func_name:
            # Compile arguments into temporaries first to avoid clobbering R0.
            args = inner[1:]
            arg_regs = []
            addr_backfills: List[Tuple[str, int, int]] = []
            for arg in args[:8]:
                addr_info = self._addr_of_local_scalar(arg)
                if addr_info:
                    name, type_str = addr_info
                    addr_reg = self._ensure_addr_var(name, type_str)
                    val_reg = self.ctx.get_reg(name)
                    size = self.ctx.get_type_size(type_str)
                    if val_reg is not None:
                        self._emit_store_by_size(addr_reg, val_reg, size)
                    tmp = self.ctx.alloc_reg()
                    self.emitter.emit_mov(tmp, addr_reg)
                    arg_regs.append(tmp)
                    addr_backfills.append((name, addr_reg, size))
                    continue
                tmp = self.ctx.alloc_reg()
                self.compile_expr(arg, tmp)
                arg_regs.append(tmp)

            # Save caller registers (R1-R7); R0 is reserved for args/return.
            for r in range(1, 8):
                self.emitter.emit_push(r)

            # Move temporaries into call argument registers R0-R7.
            for i, tmp in enumerate(arg_regs):
                if tmp != i:
                    self.emitter.emit_mov(i, tmp)
            
            # Use dedicated opcodes for memory functions
            if func_name in ('malloc', 'realloc'):
                # ALLOC: R0 = alloc(R0)
                self.emitter.emit_alloc()
            elif func_name == 'free':
                # FREE: free(R0)
                self.emitter.emit_free()
            elif func_name == 'calloc':
                # CALLOC: R0 = calloc(R0, R1)
                self.emitter.emit_calloc()
            elif func_name == 'memset':
                # MEMSET: memset(R0, R1, R2)
                self.emitter.emit_memset()
            elif func_name == 'memcpy':
                # MEMCPY: memcpy(R0, R1, R2)
                self.emitter.emit_memcpy()
            else:
                # External function call via FCALL
                func_idx = self.ctx.register_func(func_name)
                self.emitter.emit_fcall(func_idx)

            # Restore caller registers
            for r in range(7, 0, -1):
                self.emitter.emit_pop(r)

            # Refresh address-taken locals after call.
            for name, addr_reg, size in addr_backfills:
                val_reg = self.ctx.get_reg(name)
                if val_reg is not None:
                    self._emit_load_by_size(val_reg, addr_reg, size)

            for tmp in reversed(arg_regs):
                self.ctx.free_reg(tmp)
            
            # Result is in R0
            if dest_reg != 0:
                self.emitter.emit_mov(dest_reg, 0)
        
        return dest_reg
    
    def compile_if(self, node: Dict):
        """Compile if statement."""
        inner = node.get("inner", [])
        if len(inner) < 2:
            return
        
        cond_node = inner[0]
        then_node = inner[1]
        else_node = inner[2] if len(inner) > 2 else None
        
        else_label = Label()
        end_label = Label()
        
        # Compile condition
        cond_reg = self.ctx.alloc_reg()
        self.compile_expr(cond_node, cond_reg)
        
        # Jump to else if zero
        temp = self.ctx.alloc_reg()
        self._emit_const(temp, 0)
        self.emitter.emit_cmp(cond_reg, temp)
        self.ctx.free_reg(temp)
        self.ctx.free_reg(cond_reg)
        
        self.emitter._emit_jump(Op.JZ, else_label)
        
        # Then block
        self.compile_stmt(then_node)
        
        if else_node:
            self.emitter._emit_jump(Op.JMP, end_label)
        
        # Else label
        self.emitter.labels[else_label.name] = else_label
        else_label.address = len(self.emitter.instructions) * 4
        
        # Else block
        if else_node:
            self.compile_stmt(else_node)
            self.emitter.labels[end_label.name] = end_label
            end_label.address = len(self.emitter.instructions) * 4
    
    def compile_while(self, node: Dict):
        """Compile while loop."""
        inner = node.get("inner", [])
        if len(inner) < 2:
            return
        
        cond_node = inner[0]
        body_node = inner[1]
        
        start_label = self.emitter.label()
        end_label = Label()
        
        self.ctx.push_loop(start_label, end_label)
        
        # Condition
        cond_reg = self.ctx.alloc_reg()
        self.compile_expr(cond_node, cond_reg)
        
        temp = self.ctx.alloc_reg()
        self._emit_const(temp, 0)
        self.emitter.emit_cmp(cond_reg, temp)
        self.ctx.free_reg(temp)
        self.ctx.free_reg(cond_reg)
        
        self.emitter._emit_jump(Op.JZ, end_label)
        
        # Body
        self.compile_stmt(body_node)
        
        # Loop back
        self.emitter._emit_jump(Op.JMP, start_label)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        self.ctx.pop_loop()
    
    def compile_for(self, node: Dict):
        """Compile for loop."""
        inner = node.get("inner", [])
        
        # for (init; cond; incr) body
        # Clang AST structure varies, need to handle different cases
        init_node = None
        cond_node = None
        incr_node = None
        body_node = None
        
        for child in inner:
            if not child:
                continue
            kind = child.get("kind", "") or ""
            if not kind or kind == "NullStmt":
                continue
            if kind in ("DeclStmt", "BinaryOperator") and init_node is None and body_node is None:
                init_node = child
            elif kind in ("BinaryOperator", "IntegerLiteral", "ImplicitCastExpr") and init_node and cond_node is None:
                cond_node = child
            elif kind == "UnaryOperator" and cond_node:
                incr_node = child
            elif kind == "CompoundStmt":
                body_node = child
        
        # Fallback: if we have 4 children, assume standard layout
        if len(inner) >= 4 and init_node is None and cond_node is None and incr_node is None and body_node is None:
            init_node = inner[0] if inner[0] and inner[0].get("kind") != "NullStmt" else None
            cond_node = inner[1] if inner[1] and inner[1].get("kind") != "NullStmt" else None
            incr_node = inner[2] if inner[2] and inner[2].get("kind") != "NullStmt" else None
            body_node = inner[3] if len(inner) > 3 else None

        if body_node is None:
            for child in reversed(inner):
                if not child:
                    continue
                kind = child.get("kind", "") or ""
                if not kind or kind == "NullStmt":
                    continue
                if child in (init_node, cond_node, incr_node):
                    continue
                body_node = child
                break
        
        # Init
        if init_node:
            self.compile_stmt(init_node)
        
        start_label = self.emitter.label()
        incr_label = Label()
        end_label = Label()
        
        self.ctx.push_loop(incr_label, end_label)
        
        # Condition
        if cond_node:
            cond_reg = self.ctx.alloc_reg()
            self.compile_expr(cond_node, cond_reg)
            
            temp = self.ctx.alloc_reg()
            self._emit_const(temp, 0)
            self.emitter.emit_cmp(cond_reg, temp)
            self.ctx.free_reg(temp)
            self.ctx.free_reg(cond_reg)
            
            self.emitter._emit_jump(Op.JZ, end_label)
        
        # Body
        if body_node:
            self.compile_stmt(body_node)
        
        # Increment
        self.emitter.labels[incr_label.name] = incr_label
        incr_label.address = len(self.emitter.instructions) * 4
        
        if incr_node:
            self.compile_stmt(incr_node)
        
        # Loop back
        self.emitter._emit_jump(Op.JMP, start_label)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        self.ctx.pop_loop()

    def compile_switch(self, node: Dict):
        """Compile switch statement with case/default labels."""
        inner = node.get("inner", [])
        if len(inner) < 2:
            return
        
        cond_node = inner[0]
        body_node = inner[1]
        
        case_labels: Dict[str, Label] = {}
        case_exprs: List[Tuple[Dict, Label]] = []
        default_label: Optional[Label] = None
        
        def collect_cases(n: Dict):
            nonlocal default_label
            if not n:
                return
            kind = n.get("kind", "")
            if kind == "CaseStmt":
                node_id = n.get("id")
                if node_id and node_id not in case_labels:
                    case_labels[node_id] = Label()
                expr = None
                inner_nodes = n.get("inner", [])
                if inner_nodes:
                    expr = inner_nodes[0]
                if expr and node_id:
                    case_exprs.append((expr, case_labels[node_id]))
                if len(inner_nodes) > 1:
                    collect_cases(inner_nodes[1])
            elif kind == "DefaultStmt":
                if default_label is None:
                    default_label = Label()
                inner_nodes = n.get("inner", [])
                if len(inner_nodes) > 1:
                    collect_cases(inner_nodes[1])
            elif kind == "CompoundStmt":
                for child in n.get("inner", []):
                    collect_cases(child)
        
        collect_cases(body_node)
        
        cond_reg = self.ctx.alloc_reg()
        self.compile_expr(cond_node, cond_reg)
        
        end_label = Label()
        
        for expr, lbl in case_exprs:
            tmp = self.ctx.alloc_reg()
            self.compile_expr(expr, tmp)
            self.emitter.emit_cmp(cond_reg, tmp)
            self.emitter._emit_jump(Op.JZ, lbl)
            self.ctx.free_reg(tmp)
        
        if default_label:
            self.emitter._emit_jump(Op.JMP, default_label)
        else:
            self.emitter._emit_jump(Op.JMP, end_label)
        
        self.ctx.push_break(end_label)
        
        def emit_body(n: Dict):
            if not n:
                return
            kind = n.get("kind", "")
            if kind == "CaseStmt":
                node_id = n.get("id")
                lbl = case_labels.get(node_id)
                if lbl:
                    self.emitter.labels[lbl.name] = lbl
                    lbl.address = len(self.emitter.instructions) * 4
                inner_nodes = n.get("inner", [])
                if len(inner_nodes) > 1:
                    emit_body(inner_nodes[1])
            elif kind == "DefaultStmt":
                if default_label:
                    self.emitter.labels[default_label.name] = default_label
                    default_label.address = len(self.emitter.instructions) * 4
                inner_nodes = n.get("inner", [])
                if len(inner_nodes) > 1:
                    emit_body(inner_nodes[1])
            elif kind == "CompoundStmt":
                for child in n.get("inner", []):
                    emit_body(child)
            else:
                self.compile_stmt(n)
        
        emit_body(body_node)
        
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        self.ctx.pop_break()
        self.ctx.free_reg(cond_reg)
    
    def compile_logical_and(self, left: Dict, right: Dict, dest_reg: int) -> int:
        """Compile && with short-circuit evaluation."""
        false_label = Label()
        end_label = Label()
        
        # Evaluate left
        self.compile_expr(left, dest_reg)
        temp = self.ctx.alloc_reg()
        self._emit_const(temp, 0)
        self.emitter.emit_cmp(dest_reg, temp)
        self.emitter._emit_jump(Op.JZ, false_label)
        
        # Evaluate right
        self.compile_expr(right, dest_reg)
        self.emitter.emit_cmp(dest_reg, temp)
        self.emitter._emit_jump(Op.JZ, false_label)
        
        # True case
        self._emit_const(dest_reg, 1)
        self.emitter._emit_jump(Op.JMP, end_label)
        
        # False case
        self.emitter.labels[false_label.name] = false_label
        false_label.address = len(self.emitter.instructions) * 4
        self._emit_const(dest_reg, 0)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        self.ctx.free_reg(temp)
        return dest_reg
    
    def compile_logical_or(self, left: Dict, right: Dict, dest_reg: int) -> int:
        """Compile || with short-circuit evaluation."""
        true_label = Label()
        end_label = Label()
        
        temp = self.ctx.alloc_reg()
        self._emit_const(temp, 0)
        
        # Evaluate left
        self.compile_expr(left, dest_reg)
        self.emitter.emit_cmp(dest_reg, temp)
        self.emitter._emit_jump(Op.JNZ, true_label)
        
        # Evaluate right
        self.compile_expr(right, dest_reg)
        self.emitter.emit_cmp(dest_reg, temp)
        self.emitter._emit_jump(Op.JNZ, true_label)
        
        # False case
        self._emit_const(dest_reg, 0)
        self.emitter._emit_jump(Op.JMP, end_label)
        
        # True case
        self.emitter.labels[true_label.name] = true_label
        true_label.address = len(self.emitter.instructions) * 4
        self._emit_const(dest_reg, 1)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        self.ctx.free_reg(temp)
        return dest_reg
    
    def compile_ternary(self, node: Dict, dest_reg: int) -> int:
        """Compile ternary operator: cond ? true : false."""
        inner = node.get("inner", [])
        if len(inner) < 3:
            return dest_reg
        
        cond_node, true_node, false_node = inner[0], inner[1], inner[2]
        
        false_label = Label()
        end_label = Label()
        
        # Condition
        self.compile_expr(cond_node, dest_reg)
        temp = self.ctx.alloc_reg()
        self._emit_const(temp, 0)
        self.emitter.emit_cmp(dest_reg, temp)
        self.ctx.free_reg(temp)
        self.emitter._emit_jump(Op.JZ, false_label)
        
        # True case
        self.compile_expr(true_node, dest_reg)
        self.emitter._emit_jump(Op.JMP, end_label)
        
        # False case
        self.emitter.labels[false_label.name] = false_label
        false_label.address = len(self.emitter.instructions) * 4
        self.compile_expr(false_node, dest_reg)
        
        # End
        self.emitter.labels[end_label.name] = end_label
        end_label.address = len(self.emitter.instructions) * 4
        
        return dest_reg
    
    def compile_array_access(self, node: Dict, dest_reg: int) -> int:
        """Compile array subscript: arr[idx]."""
        addr_reg = self.ctx.alloc_reg()
        size = self._compile_lvalue_address(node, addr_reg)
        if size > 0:
            self._emit_load_by_size(dest_reg, addr_reg, size)
        else:
            self._emit_const(dest_reg, 0)
        self.ctx.free_reg(addr_reg)
        return dest_reg
    
    def _get_decl_ref(self, node: Dict) -> Optional[str]:
        """Extract variable name from DeclRefExpr or cast."""
        kind = node.get("kind", "")
        
        if kind == "DeclRefExpr":
            return node.get("referencedDecl", {}).get("name")
        elif kind in ("ImplicitCastExpr", "CStyleCastExpr", "ParenExpr"):
            inner = node.get("inner", [])
            if inner:
                return self._get_decl_ref(inner[0])
        
        return None
