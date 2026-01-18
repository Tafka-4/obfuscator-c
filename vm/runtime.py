"""
VM Runtime Template - C++ Interpreter Generator
"""

import random
import string
from typing import List
from .opcodes import Op, Reg, OpcodeShuffler, VM_REG_COUNT


def _rnd_name():
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


class VMRuntimeGenerator:
    """
    Generates obfuscated C++ VM interpreter code.
    """
    
    def __init__(self, shuffler: OpcodeShuffler = None):
        self.shuffler = shuffler or OpcodeShuffler()
        
        # Obfuscated names - generated once and reused
        self.vm_struct = _rnd_name()
        self.regs_name = _rnd_name()
        self.stack_name = _rnd_name()
        self.sp_name = _rnd_name()
        self.ip_name = _rnd_name()
        self.flags_name = _rnd_name()
        self.bytecode_name = _rnd_name()
        self.bc_len_name = _rnd_name()
        self.run_fn = _rnd_name()
        self.run_decoded_fn = _rnd_name()
        self.step_fn = _rnd_name()
        self.decrypt_fn = _rnd_name()
        
        # Heap management names
        self.heap_name = _rnd_name()
        self.heap_bitmap = _rnd_name()
        self.heap_alloc = _rnd_name()
        self.heap_free = _rnd_name()
        self.heap_calloc = _rnd_name()
        
        # External function call table name
        self.func_table_name = _rnd_name()
        
        # Recursion depth counter name
        self.depth_name = _rnd_name()
    
    def generate_header(self) -> str:
        """Generate VM header with struct definition and internal heap."""
        return f'''
// VM Protection Runtime
#include <cstdint>
#include <cstring>
#include <cstdlib>

#define VM_STACK_SIZE 4096
#define VM_REG_COUNT {VM_REG_COUNT}
#define VM_HEAP_SIZE (1024 * 1024)    // 1MB internal heap
#define VM_BLOCK_SIZE 64      // 64-byte blocks
#define VM_BLOCK_COUNT (VM_HEAP_SIZE / VM_BLOCK_SIZE)  // 1024 blocks

// VM internal heap - completely self-contained
static uint8_t {self.heap_name}[VM_HEAP_SIZE];
static uint8_t {self.heap_bitmap}[VM_BLOCK_COUNT / 8];  // Bitmap: 1 bit per block

// Simple block allocator - returns pointer into VM heap
static void* {self.heap_alloc}(size_t size) {{
    if (size == 0) return nullptr;
    size_t total = size + sizeof(uint32_t);
    size_t blocks_needed = (total + VM_BLOCK_SIZE - 1) / VM_BLOCK_SIZE;
    
    // Find consecutive free blocks
    size_t consecutive = 0;
    size_t start_block = 0;
    
    for (size_t i = 0; i < VM_BLOCK_COUNT; i++) {{
        size_t byte_idx = i / 8;
        size_t bit_idx = i % 8;
        bool is_used = ({self.heap_bitmap}[byte_idx] >> bit_idx) & 1;
        
        if (!is_used) {{
            if (consecutive == 0) start_block = i;
            consecutive++;
            if (consecutive >= blocks_needed) {{
                // Mark blocks as used
                for (size_t j = start_block; j <= i; j++) {{
                    size_t bj = j / 8;
                    size_t bi = j % 8;
                    {self.heap_bitmap}[bj] |= (1 << bi);
                }}
                // Store block count at beginning for free()
                uint32_t* header = (uint32_t*)&{self.heap_name}[start_block * VM_BLOCK_SIZE];
                *header = (uint32_t)blocks_needed;
                return header + 1;  // Return after header
            }}
        }} else {{
            consecutive = 0;
        }}
    }}
    return nullptr;  // Out of memory
}}

static void {self.heap_free}(void* ptr) {{
    if (!ptr) return;
    
    // Get header (stored before user data)
    uint32_t* header = ((uint32_t*)ptr) - 1;
    
    // Validate pointer is within heap
    if ((uint8_t*)header < {self.heap_name} || (uint8_t*)header >= {self.heap_name} + VM_HEAP_SIZE) return;
    
    uint32_t blocks = *header;
    size_t start_block = ((uint8_t*)header - {self.heap_name}) / VM_BLOCK_SIZE;
    
    // Mark blocks as free
    for (size_t i = 0; i < blocks && (start_block + i) < VM_BLOCK_COUNT; i++) {{
        size_t bj = (start_block + i) / 8;
        size_t bi = (start_block + i) % 8;
        {self.heap_bitmap}[bj] &= ~(1 << bi);
    }}
}}

static void* {self.heap_calloc}(size_t count, size_t size) {{
    size_t total = count * size;
    void* ptr = {self.heap_alloc}(total);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}}

struct {self.vm_struct} {{
    uint64_t {self.regs_name}[VM_REG_COUNT];
    uint8_t {self.stack_name}[VM_STACK_SIZE];
    uint32_t {self.sp_name};
    uint32_t {self.ip_name};
    uint32_t {self.flags_name};  // bit 0: zero, bit 1: sign, bit 2: carry
    const uint8_t* {self.bytecode_name};
    uint32_t {self.bc_len_name};
}};

// External function pointer type for FCALL (takes up to 8 int64_t args)
typedef int64_t (*_vm_func_ptr_t)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);

// PLT/GOT: Extern declaration for global function table (defined after bytecode arrays)
extern _vm_func_ptr_t {self.func_table_name}[];

// VM recursion depth control
static int {self.depth_name} = 0;
#define VM_MAX_DEPTH 10
'''
    
    def generate_decrypt_routine(self) -> str:
        """Generate TEA-CTR bytecode decryption routine."""
        tea_fn = _rnd_name()
        out = _rnd_name()
        inp = _rnd_name()
        length = _rnd_name()
        key = _rnd_name()
        nonce = _rnd_name()
        counter = _rnd_name()
        offset = _rnd_name()
        v0 = _rnd_name()
        v1 = _rnd_name()
        sum_name = _rnd_name()
        delta = _rnd_name()
        ks = _rnd_name()
        i = _rnd_name()
        
        return f'''
static inline void {tea_fn}(uint32_t* {v0}, uint32_t* {v1}, const uint32_t* {key}) {{
    uint32_t {sum_name} = 0;
    const uint32_t {delta} = 0x9E3779B9;
    for (int {i} = 0; {i} < 32; {i}++) {{
        {sum_name} += {delta};
        *{v0} += (((*{v1} << 4) + {key}[0]) ^ (*{v1} + {sum_name}) ^ ((*{v1} >> 5) + {key}[1]));
        *{v1} += (((*{v0} << 4) + {key}[2]) ^ (*{v0} + {sum_name}) ^ ((*{v0} >> 5) + {key}[3]));
    }}
}}

static inline void {self.decrypt_fn}(uint8_t* {out}, const uint8_t* {inp}, uint32_t {length}, const uint32_t* {key}, uint64_t {nonce}) {{
    uint64_t {counter} = {nonce};
    uint32_t {offset} = 0;
    while ({offset} < {length}) {{
        uint32_t {v0} = (uint32_t)({counter} & 0xFFFFFFFF);
        uint32_t {v1} = (uint32_t)({counter} >> 32);
        {tea_fn}(&{v0}, &{v1}, {key});
        uint8_t {ks}[8];
        memcpy({ks}, &{v0}, 4);
        memcpy({ks} + 4, &{v1}, 4);
        for (uint32_t {i} = 0; {i} < 8 && {offset} < {length}; {i}++, {offset}++) {{
            {out}[{offset}] = {inp}[{offset}] ^ {ks}[{i}];
        }}
        {counter}++;
    }}
}}
'''
    
    def generate_step_function(self) -> str:
        """Generate the main VM step function with all opcode handlers."""
        vm = _rnd_name()
        op = _rnd_name()
        dst = _rnd_name()
        src1 = _rnd_name()
        src2 = _rnd_name()
        imm = _rnd_name()
        
        # Generate handler cases with shuffled opcodes
        handlers = []
        
        # Data Movement handlers
        handlers.append(self._gen_handler(Op.NOP, f"(void)0;"))  # NOP - empty statement
        handlers.append(self._gen_handler(Op.MOV, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}];"))
        handlers.append(self._gen_handler(Op.MOVI, f"{vm}->{self.regs_name}[{dst}] = (uint64_t)(uint16_t){imm};"))
        handlers.append(self._gen_handler(Op.LOAD, f"""
            uint64_t _tmp64 = 0;
            memcpy(&_tmp64, (void*)(uintptr_t){vm}->{self.regs_name}[{src1}], sizeof(_tmp64));
            {vm}->{self.regs_name}[{dst}] = _tmp64;
        """))
        handlers.append(self._gen_handler(Op.STORE, f"""
            uint64_t _tmp64 = {vm}->{self.regs_name}[{src1}];
            memcpy((void*)(uintptr_t){vm}->{self.regs_name}[{dst}], &_tmp64, sizeof(_tmp64));
        """))
        handlers.append(self._gen_handler(Op.LOAD8, f"{vm}->{self.regs_name}[{dst}] = *(uint8_t*)((uintptr_t){vm}->{self.regs_name}[{src1}]);"))
        handlers.append(self._gen_handler(Op.STORE8, f"*(uint8_t*)((uintptr_t){vm}->{self.regs_name}[{dst}]) = (uint8_t){vm}->{self.regs_name}[{src1}];"))
        handlers.append(self._gen_handler(Op.LOAD16, f"""
            uint16_t _tmp16 = 0;
            memcpy(&_tmp16, (void*)(uintptr_t){vm}->{self.regs_name}[{src1}], sizeof(_tmp16));
            {vm}->{self.regs_name}[{dst}] = _tmp16;
        """))
        handlers.append(self._gen_handler(Op.STORE16, f"""
            uint16_t _tmp16 = (uint16_t){vm}->{self.regs_name}[{src1}];
            memcpy((void*)(uintptr_t){vm}->{self.regs_name}[{dst}], &_tmp16, sizeof(_tmp16));
        """))
        handlers.append(self._gen_handler(Op.PUSH, f"""
            {vm}->{self.sp_name} -= 8;
            *(uint64_t*)(&{vm}->{self.stack_name}[{vm}->{self.sp_name}]) = {vm}->{self.regs_name}[{src1}];
        """))
        handlers.append(self._gen_handler(Op.POP, f"""
            {vm}->{self.regs_name}[{dst}] = *(uint64_t*)(&{vm}->{self.stack_name}[{vm}->{self.sp_name}]);
            {vm}->{self.sp_name} += 8;
        """))
        
        # Arithmetic handlers
        handlers.append(self._gen_handler(Op.ADD, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] + {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.ADDI, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{dst}] + (uint64_t)(int16_t){imm};"))
        handlers.append(self._gen_handler(Op.SUB, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] - {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.MUL, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] * {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.DIV, f"""
            if ({vm}->{self.regs_name}[{src2}] != 0) {{
                int64_t _a = (int64_t){vm}->{self.regs_name}[{src1}];
                int64_t _b = (int64_t){vm}->{self.regs_name}[{src2}];
                if (!(_a == INT64_MIN && _b == -1)) {{
                    {vm}->{self.regs_name}[{dst}] = (uint64_t)(_a / _b);
                }}
            }}
        """))
        handlers.append(self._gen_handler(Op.MOD, f"""
            if ({vm}->{self.regs_name}[{src2}] != 0) {{
                int64_t _a = (int64_t){vm}->{self.regs_name}[{src1}];
                int64_t _b = (int64_t){vm}->{self.regs_name}[{src2}];
                if (_a == INT64_MIN && _b == -1) {{
                    {vm}->{self.regs_name}[{dst}] = 0;
                }} else {{
                    {vm}->{self.regs_name}[{dst}] = (uint64_t)(_a % _b);
                }}
            }}
        """))
        handlers.append(self._gen_handler(Op.NEG, f"{vm}->{self.regs_name}[{dst}] = (uint64_t)(0 - {vm}->{self.regs_name}[{src1}]);"))
        handlers.append(self._gen_handler(Op.INC, f"{vm}->{self.regs_name}[{dst}]++;"))
        handlers.append(self._gen_handler(Op.DEC, f"{vm}->{self.regs_name}[{dst}]--;"))
        
        # Bitwise handlers
        handlers.append(self._gen_handler(Op.AND, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] & {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.OR, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] | {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.XOR, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] ^ {vm}->{self.regs_name}[{src2}];"))
        handlers.append(self._gen_handler(Op.NOT, f"{vm}->{self.regs_name}[{dst}] = ~{vm}->{self.regs_name}[{src1}];"))
        handlers.append(self._gen_handler(Op.SHL, f"{vm}->{self.regs_name}[{dst}] = {vm}->{self.regs_name}[{src1}] << ({vm}->{self.regs_name}[{src2}] & 63);"))
        handlers.append(self._gen_handler(Op.SHR, f"{vm}->{self.regs_name}[{dst}] = (uint64_t){vm}->{self.regs_name}[{src1}] >> ({vm}->{self.regs_name}[{src2}] & 63);"))
        
        # Control flow handlers
        cmp_var = _rnd_name()  # Create once for consistent use
        handlers.append(self._gen_handler(Op.CMP, f"""
            int64_t {cmp_var}_a = (int64_t){vm}->{self.regs_name}[{src1}];
            int64_t {cmp_var}_b = (int64_t){vm}->{self.regs_name}[{src2}];
            {vm}->{self.flags_name} = 0;
            if ({cmp_var}_a == {cmp_var}_b) {vm}->{self.flags_name} |= 1;
            if ({cmp_var}_a < {cmp_var}_b) {vm}->{self.flags_name} |= 2;
        """))
        handlers.append(self._gen_handler(Op.JMP, f"{vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JZ, f"if ({vm}->{self.flags_name} & 1) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JNZ, f"if (!({vm}->{self.flags_name} & 1)) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JL, f"if ({vm}->{self.flags_name} & 2) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JLE, f"if (({vm}->{self.flags_name} & 2) || ({vm}->{self.flags_name} & 1)) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JG, f"if (!({vm}->{self.flags_name} & 2) && !({vm}->{self.flags_name} & 1)) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.JGE, f"if (!({vm}->{self.flags_name} & 2)) {vm}->{self.ip_name} = {imm};"))
        handlers.append(self._gen_handler(Op.CALL, f"""
            {vm}->{self.sp_name} -= 8;
            *(uint32_t*)(&{vm}->{self.stack_name}[{vm}->{self.sp_name}]) = {vm}->{self.ip_name};
            {vm}->{self.ip_name} = {imm};
        """))
        handlers.append(self._gen_handler(Op.RET, f"""
            {vm}->{self.ip_name} = *(uint32_t*)(&{vm}->{self.stack_name}[{vm}->{self.sp_name}]);
            {vm}->{self.sp_name} += 8;
        """))
        
        # Memory Management opcodes
        handlers.append(self._gen_handler(Op.ALLOC, f"""
            {vm}->{self.regs_name}[0] = (uint64_t)(uintptr_t){self.heap_alloc}((size_t){vm}->{self.regs_name}[0]);
        """))
        handlers.append(self._gen_handler(Op.FREE, f"""
            {self.heap_free}((void*)(uintptr_t){vm}->{self.regs_name}[0]);
            {vm}->{self.regs_name}[0] = 0;
        """))
        handlers.append(self._gen_handler(Op.CALLOC, f"""
            {vm}->{self.regs_name}[0] = (uint64_t)(uintptr_t){self.heap_calloc}((size_t){vm}->{self.regs_name}[0], (size_t){vm}->{self.regs_name}[1]);
        """))
        handlers.append(self._gen_handler(Op.MEMSET, f"""
            memset((void*)(uintptr_t){vm}->{self.regs_name}[0], (int){vm}->{self.regs_name}[1], (size_t){vm}->{self.regs_name}[2]);
        """))
        handlers.append(self._gen_handler(Op.MEMCPY, f"""
            memcpy((void*)(uintptr_t){vm}->{self.regs_name}[0], (void*)(uintptr_t){vm}->{self.regs_name}[1], (size_t){vm}->{self.regs_name}[2]);
        """))
        
        # External function call - uses function pointer table
        handlers.append(self._gen_handler(Op.FCALL, f"""
            if ({self.func_table_name} && {self.func_table_name}[{dst}]) {{
                {vm}->{self.regs_name}[0] = (uint64_t){self.func_table_name}[{dst}](
                    (int64_t){vm}->{self.regs_name}[0], (int64_t){vm}->{self.regs_name}[1], (int64_t){vm}->{self.regs_name}[2], (int64_t){vm}->{self.regs_name}[3],
                    (int64_t){vm}->{self.regs_name}[4], (int64_t){vm}->{self.regs_name}[5], (int64_t){vm}->{self.regs_name}[6], (int64_t){vm}->{self.regs_name}[7]
                );
            }}
        """))
        
        # Special - HALT returns from function, no break needed
        handlers.append(self._gen_handler(Op.HALT, f"return -1;", needs_break=False))
        
        cases = "\n".join(handlers)
        
        return f'''
static int {self.step_fn}({self.vm_struct}* {vm}) {{
    if ({vm}->{self.ip_name} >= {vm}->{self.bc_len_name}) return -1;
    
    uint8_t {op} = {vm}->{self.bytecode_name}[{vm}->{self.ip_name}++];
    uint8_t {dst} = {vm}->{self.bytecode_name}[{vm}->{self.ip_name}++];
    uint8_t {src1} = {vm}->{self.bytecode_name}[{vm}->{self.ip_name}++];
    uint8_t {src2} = {vm}->{self.bytecode_name}[{vm}->{self.ip_name}++];
    uint16_t {imm} = {src1} | ((uint16_t){src2} << 8);
    
    switch ({op}) {{
{cases}
        default: break;
    }}
    
    return 0;
}}
'''
    
    def _gen_handler(self, op: Op, code: str, needs_break: bool = True) -> str:
        """Generate a single opcode handler case."""
        encoded = self.shuffler.encode(op)
        break_stmt = " break;" if needs_break else ""
        return f"        case 0x{encoded:02X}: {{ {code.strip()}{break_stmt} }}"
    
    def generate_run_function(self) -> str:
        """Generate the main VM run function."""
        vm = _rnd_name()
        bc = _rnd_name()
        bc_len = _rnd_name()
        k = _rnd_name()
        nonce = _rnd_name()
        
        return f'''
static int64_t {self.run_fn}(const uint8_t* {bc}, uint32_t {bc_len}, const uint32_t* {k}, uint64_t {nonce}, int64_t* args, int argc) {{
    // Recursion depth check
    if ({self.depth_name} >= VM_MAX_DEPTH) return 0;
    {self.depth_name}++;

    uint8_t* _vm_decoded = nullptr;
    if ({bc_len}) {{
        _vm_decoded = (uint8_t*)malloc({bc_len});
        if (!_vm_decoded) {{
            {self.depth_name}--;
            return 0;
        }}
        {self.decrypt_fn}(_vm_decoded, {bc}, {bc_len}, {k}, {nonce});
    }}
    
    {self.vm_struct} {vm};
    memset(&{vm}, 0, sizeof({vm}));
    
    {vm}.{self.bytecode_name} = _vm_decoded ? _vm_decoded : {bc};
    {vm}.{self.bc_len_name} = {bc_len};
    {vm}.{self.sp_name} = VM_STACK_SIZE;
    {vm}.{self.ip_name} = 0;
    
    // Copy arguments to registers
    for (int i = 0; i < argc && i < 8; i++) {{
        {vm}.{self.regs_name}[i] = (uint64_t)args[i];
    }}
    
    // Execute
    while ({self.step_fn}(&{vm}) == 0);
    
    int64_t result = (int64_t){vm}.{self.regs_name}[0];
    if (_vm_decoded) free(_vm_decoded);
    {self.depth_name}--;
    return result;
}}
'''

    def generate_run_decoded_function(self) -> str:
        """Generate a VM run function for already-decoded bytecode."""
        vm = _rnd_name()
        bc = _rnd_name()
        bc_len = _rnd_name()

        return f'''
static int64_t {self.run_decoded_fn}(const uint8_t* {bc}, uint32_t {bc_len}, int64_t* args, int argc) {{
    // Recursion depth check
    if ({self.depth_name} >= VM_MAX_DEPTH) return 0;
    {self.depth_name}++;

    {self.vm_struct} {vm};
    memset(&{vm}, 0, sizeof({vm}));

    {vm}.{self.bytecode_name} = {bc};
    {vm}.{self.bc_len_name} = {bc_len};
    {vm}.{self.sp_name} = VM_STACK_SIZE;
    {vm}.{self.ip_name} = 0;

    // Copy arguments to registers
    for (int i = 0; i < argc && i < 8; i++) {{
        {vm}.{self.regs_name}[i] = (uint64_t)args[i];
    }}

    // Execute
    while ({self.step_fn}(&{vm}) == 0);

    int64_t result = (int64_t){vm}.{self.regs_name}[0];
    {self.depth_name}--;
    return result;
}}
'''
    
    def generate_full_runtime(self) -> str:
        """Generate complete VM runtime code."""
        code = self.generate_header()
        code += self.generate_decrypt_routine()
        code += self.generate_step_function()
        code += self.generate_run_function()
        code += self.generate_run_decoded_function()
        return code


def generate_vm_runtime(shuffler: OpcodeShuffler = None) -> str:
    """Convenience function to generate VM runtime."""
    gen = VMRuntimeGenerator(shuffler)
    return gen.generate_full_runtime()
