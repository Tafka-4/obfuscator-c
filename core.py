
import os
import random
import re
import shutil
import time
from . import config
from . import ast_utils
from . import cpp_gen
from .passes import mba, dead_code, control_flow, strings, renaming, const_encoding
from .passes import advanced
from .vm import ASTCompiler, VMRuntimeGenerator, OpcodeShuffler
from .vm.struct_analyzer import StructLayoutAnalyzer
from .ast_passes import OpaquePredicates, MBAPass, InstructionSubstitution, BogusControlFlow, GraphSplit

# VM Protection marker: add "// VM_PROTECT" comment before functions to virtualize

def find_matching_brace(text, start_offset):
    """Find the closing brace matching the opening brace at start_offset."""
    if start_offset >= len(text) or text[start_offset] != '{':
        return -1
    depth = 0
    in_string = False
    in_char = False
    escape_next = False
    i = start_offset
    while i < len(text):
        c = text[i]
        if escape_next:
            escape_next = False
            i += 1
            continue
        if c == '\\':
            escape_next = True
            i += 1
            continue
        if c == '"' and not in_char:
            in_string = not in_string
        elif c == "'" and not in_string:
            in_char = not in_char
        elif not in_string and not in_char:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _is_decl_ref_like(node):
    if not node:
        return False
    kind = node.get("kind", "")
    if kind == "DeclRefExpr":
        return True
    if kind in ("ImplicitCastExpr", "CStyleCastExpr", "ParenExpr"):
        inner = node.get("inner", [])
        if inner:
            return _is_decl_ref_like(inner[0])
    return False


def _has_vm_unsupported_nodes(func_node):
    unsupported_kinds = {
        "GotoStmt",
        "IndirectGotoStmt",
        "LabelStmt",
        "AsmStmt",
        "CXXTryStmt",
        "CXXCatchStmt",
    }

    stack = [func_node]
    while stack:
        node = stack.pop()
        kind = node.get("kind", "")

        if kind in unsupported_kinds:
            return True

        stack.extend(node.get("inner", []) or [])

    return False


class Obfuscator:
    def __init__(self):
        self.symbol_map = {}
        self.vm_processed_files = set()
        self.graph_nodes = []
        self.options = {
            'vm_enabled': True,
            'vm_functions': None,  # Use VM_PROTECTED_FUNCTIONS if None
            'vm_exclude': [],
            'disabled_passes': [],
            'enable_only': None,
            'verbose': False,
            'quiet': False,
            'dry_run': False,
        }
    
    def log(self, msg, level='info'):
        """Log message respecting verbosity settings."""
        if self.options.get('quiet') and level != 'error':
            return
        print(msg)
    
    def is_pass_enabled(self, pass_name):
        """Check if a pass is enabled."""
        if self.options.get('enable_only'):
            return pass_name in self.options['enable_only']
        return pass_name not in self.options.get('disabled_passes', [])

    def run(self, specific_files=None):
        self.log(f"[*] Starting Obfuscation...")
        self.log(f"    Source Dirs: {config.SOURCE_DIRS}")
        self.log(f"    Build Dir: {config.BUILD_DIR}")
        
        if os.path.exists(config.BUILD_DIR):
            shutil.rmtree(config.BUILD_DIR)

        main_src = config.SOURCE_DIRS[0]
        dest_src = os.path.join(config.BUILD_DIR, os.path.basename(main_src))
        ignore_names = (
            "build",
            "CMakeFiles",
            "CMakeCache.txt",
            "cmake_install.cmake",
        )
        shutil.copytree(main_src, dest_src, ignore=shutil.ignore_patterns(*ignore_names))

        # Copy CMakeLists.txt if exists
        if os.path.exists("CMakeLists.txt"):
            shutil.copy("CMakeLists.txt", config.BUILD_DIR)
            
        # Copy resources (admin.info, flag)
        for res in ["admin.info", "flag"]:
            if os.path.exists(res):
                shutil.copy(res, config.BUILD_DIR)
        
        # Generate Makefile
        makefile_content = """CXX = g++
CXXFLAGS = -std=c++17 -I src -I src/crypto
TARGET = server
SOURCES = $(wildcard src/*.cpp) $(wildcard src/crypto/*.cpp)

all: $(TARGET)

$(TARGET): $(SOURCES)
\t$(CXX) $(CXXFLAGS) $(SOURCES) -o $(TARGET)

clean:
\trm -f $(TARGET)
"""
        with open(os.path.join(config.BUILD_DIR, "Makefile"), "w") as f:
            f.write(makefile_content)

        cpp_gen.create_obfuscator_header()

        # Generate Graph Wall
        from .graph_gen import GraphGenerator
        print("    [+] Generating Graph Wall...")
        graph_gen = GraphGenerator(num_nodes=100, layers=10)
        graph_gen.generate()
        self.graph_nodes = [node.name for node in graph_gen.nodes]
        h_code, cpp_code = graph_gen.to_cpp()
        
        with open(os.path.join(dest_src, "graph_wall.h"), "w") as f:
            f.write(h_code)
        with open(os.path.join(dest_src, "graph_wall.cpp"), "w") as f:
            f.write(cpp_code)
            
        files_to_process = []
        if specific_files:
            files_to_process = [os.path.join(dest_src, f) for f in specific_files] 
        else:
            skip_dirs = {"build", "CMakeFiles", ".git", ".cache"}
            for root, dirs, files in os.walk(dest_src):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                if any(part in skip_dirs for part in root.split(os.sep)):
                    continue
                for file in files:
                    if file == "obfuscator_full.hpp": continue
                    ext = os.path.splitext(file)[1]
                    if ext in config.VALID_EXTENSIONS:
                        files_to_process.append(os.path.join(root, file))
        
        # Inject Graph Entry into main.cpp
        main_cpp_path = os.path.join(dest_src, "main.cpp")
        if os.path.exists(main_cpp_path):
             with open(main_cpp_path, "r") as f:
                 main_content = f.read()
             
             if '#include "graph_wall.h"' not in main_content:
                 main_content = '#include "graph_wall.h"\n' + main_content
                 
             if "run_graph_wall();" not in main_content:
                 # Find main start
                 main_idx = main_content.find("int main")
                 if main_idx != -1:
                     brace_idx = main_content.find("{", main_idx)
                     if brace_idx != -1:
                         main_content = main_content[:brace_idx+1] + "\n    run_graph_wall();" + main_content[brace_idx+1:]
                         
             with open(main_cpp_path, "w") as f:
                 f.write(main_content)

        print(f"    [i] Files to process: {files_to_process}")

        # 2. Collect Symbols
        print("    [Phase 0] Symbol Discovery")
        for file_path in files_to_process:
             ast = ast_utils.get_ast(file_path)
             if ast:
                 symbols = renaming.Renaming.find_all_declarations(ast, "", file_path, self.symbol_map)
                 self.symbol_map.update(symbols)
                 print(f"    [DEBUG] Analyzed {file_path}, found {len(symbols)} new symbols.")
             else:
                 print(f"    [WARN] No AST for {file_path}")
        
        print(f"    [+] Discovered {len(self.symbol_map)} total symbols to rename.")

        # 3.3 Graph-based function splitting (before VM protection)
        if self.is_pass_enabled("graph-split") and self.graph_nodes:
            main_cpp_path = os.path.join(dest_src, "main.cpp")
            if os.path.exists(main_cpp_path):
                self._apply_graph_split_standalone(main_cpp_path)

        # 3.5. VM Protection pre-pass (before any obfuscation passes)
        # This ensures VM compilation sees the original AST without injected gotos/labels.
        vm_enabled = self.options.get('vm_enabled', True) if hasattr(self, 'options') else True
        if vm_enabled:
            print("    [Phase 0.5] VM Protection (pre-pass)")
            main_cpp_path = os.path.join(dest_src, "main.cpp")
            if os.path.exists(main_cpp_path):
                self._apply_vm_protection_standalone(main_cpp_path)
                self.vm_processed_files.add(os.path.abspath(main_cpp_path))

        # 3. Phase 1: AST Passes (Strings, Calls, ICFF, Junk)
        # These passes require valid AST. Logic complexity changes.
        print("    [Phase 1] AST-Based Obfuscation")
        for file_path in files_to_process:
            if "graph_wall.cpp" in file_path:
                print(f"    Skipping AST phase for generated file: {file_path}")
                continue
            if os.path.abspath(file_path) in self.vm_processed_files:
                print(f"    Skipping AST phase for VM-protected file: {file_path}")
                continue
            self.process_file_ast_phase(file_path)
            
        # 4. Phase 2: Renaming & Regex (MBA, DeadCodeSimple, Opaque, Rename)
        # These passes are causing compilation errors due to lack of type info (MBA) and context (Renaming).
        # Disabling them to ensure build stability.
        print("    [Phase 2] Text-Based Obfuscation & Renaming")
        for file_path in files_to_process:
             if os.path.abspath(file_path) in self.vm_processed_files:
                 print(f"    Skipping text phase for VM-protected file: {file_path}")
                 continue
             self.process_file_text_phase(file_path)

        # 5. Phase 3: VM Protection - runs LAST after ALL other passes
        if vm_enabled:
            print("    [Phase 3] VM Protection")
            for file_path in files_to_process:
                if os.path.abspath(file_path) in self.vm_processed_files:
                    continue
                if "main.cpp" in file_path:  # Only VM protect main.cpp
                    self._apply_vm_protection_standalone(file_path)
                    self.vm_processed_files.add(os.path.abspath(file_path))

        print("[*] Obfuscation Complete.")

    def process_file_ast_phase(self, file_path):
        print(f"    Processing (AST) {file_path}...")
        with open(file_path, "rb") as f:
            content = f.read()
            
        def refresh_ast(curr_content, step_name):
            with open(file_path, "wb") as f:
                f.write(curr_content)
            ast = ast_utils.get_ast(file_path)
            if not ast:
                print(f"    [WARN] AST generation failed at step: {step_name}")
            return ast

        # Verify header injection first (needed for Strings pass OBFUSCATE macro)
        # Check bytes
        if b'#include "obfuscator_full.hpp"' not in content:
            last_include_idx = content.rfind(b"#include")
            if last_include_idx != -1:
                end_of_line = content.find(b"\n", last_include_idx)
                content = content[:end_of_line+1] + b'\n#include "obfuscator_full.hpp"\n' + content[end_of_line+1:]
            else:
                 content = b'#include "obfuscator_full.hpp"\n' + content
            # Save so refresh_ast sees it
            with open(file_path, "wb") as f:
                 f.write(content)
        
        # Pass 2: Strings
        ast = refresh_ast(content, "Strings")
        if ast:
            content = strings.StringEncryption.encrypt_strings(content, ast, file_path)
            with open(file_path, "wb") as f: f.write(content) # Save for next step

        ast = refresh_ast(content, "Calls")
        if ast:
            text_content = content.decode('utf-8', errors='ignore')
            new_text = renaming.Renaming.obfuscate_calls(text_content, ast, self.symbol_map)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
            
        # Pass 4: ICFF
        ast = refresh_ast(content, "ICFF")
        if ast:
            text_content = content.decode('utf-8', errors='ignore')
            new_text = control_flow.ControlFlow.apply_icff(text_content, ast)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
            
        # Pass 5: Junk Injection
        ast = refresh_ast(content, "Junk")
        if ast:
            text_content = content.decode('utf-8', errors='ignore')
            new_text = dead_code.DeadCode.inject_junk_ast(text_content, ast, file_path)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
        
        # VM Protection now runs as Phase 3 after all other passes

    def _apply_vm_protection_standalone(self, file_path):
        """Apply VM protection independently in Phase 3."""
        with open(file_path, "rb") as f:
            content = f.read()
        
        ast = ast_utils.get_ast(file_path)
        if not ast:
            print(f"        [VM] No AST for {file_path}")
            return
        
        def refresh_ast_local(curr_content, step_name):
            with open(file_path, "wb") as f:
                f.write(curr_content)
            return ast_utils.get_ast(file_path)
        
        self._apply_vm_protection(file_path, content, refresh_ast_local)

    def _apply_graph_split_standalone(self, file_path):
        """Apply graph-based function splitting to marked functions."""
        with open(file_path, "rb") as f:
            content = f.read()

        ast = ast_utils.get_ast(file_path)
        if not ast:
            print(f"    [GraphSplit] No AST for {file_path}")
            return

        splitter = GraphSplit(self.graph_nodes)
        new_content = splitter.apply(content, ast, file_path)
        if splitter.edits:
            print(f"    [GraphSplit] Applied to {len(splitter.edits)} function(s) in {file_path}")
        if new_content != content:
            with open(file_path, "wb") as f:
                f.write(new_content)

    def _apply_vm_protection(self, file_path, content, refresh_ast):
        """Apply VM protection to functions marked with // VM_PROTECT."""
        ast = refresh_ast(content, "VMProtect")
        if not ast:
            return content
            
        text_content = content.decode('utf-8', errors='ignore')
        shuffler = OpcodeShuffler()
        compiler = ASTCompiler(shuffler)
        runtime_gen = VMRuntimeGenerator(shuffler)
        
        # Analyze struct layouts for proper member offset calculation
        struct_analyzer = StructLayoutAnalyzer()
        struct_layouts = struct_analyzer.analyze(ast)
        if struct_layouts:
            print(f"        [VM] Analyzed {len(struct_layouts)} struct layouts")
        
        funcs = ast_utils.find_nodes(ast, "FunctionDecl")
        vm_bytecodes = []

        def _is_vm_file(func_node):
            if ast_utils.is_in_file(func_node, file_path):
                return True
            loc = func_node.get("loc") or func_node.get("range", {}).get("begin") or {}
            if loc.get("includedFrom"):
                return False
            # If file info is missing but we have a concrete offset, assume main file.
            if loc.get("file"):
                return os.path.abspath(loc.get("file")) == os.path.abspath(file_path)
            return loc.get("offset") is not None
        
        print(f"        [VM] Scanning {len(funcs)} functions for VM_PROTECT marker...")
        vm_exclude = set(self.options.get('vm_exclude', []))
        
        for func in funcs:
            func_name = func.get("name")
            if not func_name:
                continue

            if not _is_vm_file(func):
                continue
            
            
            has_body = any(child.get("kind") == "CompoundStmt" for child in func.get("inner", []))
            if not has_body:
                continue
            
            # Check for // VM_PROTECT marker before function
            loc = func.get("loc", {})
            line = loc.get("line", 0)
            if line > 1:
                lines = text_content.split('\n')
                marker_found = False
                for check_line in range(max(0, line - 5), line - 1):
                    if check_line < len(lines) and '// VM_PROTECT' in lines[check_line]:
                        marker_found = True
                        break
                if not marker_found:
                    continue
            else:
                continue

            if func_name in vm_exclude:
                print(f"        [VM] Skipping: {func_name} (excluded)")
                continue

            if _has_vm_unsupported_nodes(func):
                print(f"        [VM] Skipping: {func_name} (unsupported AST for VM)")
                continue
            
            # Get body location for replacement
            body_node = None
            for child in func.get("inner", []):
                if child.get("kind") == "CompoundStmt":
                    body_node = child
                    break
            if not body_node:
                continue
                
            body_range = body_node.get("range", {})
            body_begin = body_range.get("begin", {})
            
            # Extract return type from function signature
            func_type = func.get("type", {}).get("qualType", "void")
            # Parse return type: "int (int, int)" -> "int", "void (void)" -> "void"
            return_type = func_type.split('(')[0].strip() if '(' in func_type else "void"
            is_void = return_type == "void" or return_type == ""
            
            print(f"        [VM] Protecting: {func_name} (returns: {return_type})")
            try:
                bytecode, c_array, func_table, string_literals = compiler.compile_function(func, text_content, struct_layouts=struct_layouts)
                vm_bytecodes.append({
                    'name': func_name,
                    'func_node': func,  # Store for pass 2 recompilation
                    'array': c_array,
                    'array_name': c_array.split('[')[0].split()[-1],
                    'body_begin_line': body_begin.get("line", 0),
                    'body_begin_col': body_begin.get("col", 0),
                    'return_type': return_type,
                    'is_void': is_void,
                    'func_table': func_table,  # External functions called
                    'global_vars': dict(compiler.ctx.global_vars),
                    'string_literals': dict(string_literals),
                })
                if func_table:
                    print(f"        [VM] Successfully compiled {func_name} (calls: {', '.join(func_table)})")
                else:
                    print(f"        [VM] Successfully compiled {func_name}")
            except Exception as e:
                print(f"        [VM] WARN: Compilation failed for {func_name}: {e}")
        
        if not vm_bytecodes:
            return content
        
        # ====================================================================
        # PLT/GOT: 2-PASS COMPILATION
        # ====================================================================
        
        # PASS 1 COMPLETE: Collected func_table from each function above
        # Now build GLOBAL PLT mapping from all collected func_tables
        global_plt = []  # Ordered list of unique external function names
        global_plt_indices = {}  # name -> global index
        for vm_info in vm_bytecodes:
            for func_name in vm_info.get('func_table', []):
                if func_name not in global_plt_indices:
                    global_plt_indices[func_name] = len(global_plt)
                    global_plt.append(func_name)
        
        if global_plt:
            print(f"        [VM] Global PLT: {len(global_plt)} external functions: {', '.join(global_plt)}")
        
        # PASS 2: Recompile all functions with GLOBAL PLT indices
        print(f"        [VM] Pass 2: Recompiling with global PLT indices...")
        for vm_info in vm_bytecodes:
            func_node = vm_info.get('func_node')  # Need to store this earlier!
            if func_node:
                try:
                    bytecode, c_array, _, string_literals = compiler.compile_function(func_node, text_content, global_plt_indices, struct_layouts)
                    vm_info['array'] = c_array
                    vm_info['array_name'] = c_array.split('[')[0].split()[-1]
                    vm_info['global_vars'] = dict(compiler.ctx.global_vars)
                    vm_info['string_literals'] = dict(string_literals)
                    print(f"        [VM] Recompiled: {vm_info['name']}")
                except Exception as e:
                    print(f"        [VM] WARN: Recompilation failed for {vm_info['name']}: {e}")
        
        # Generate runtime code FIRST to capture run_fn name
        runtime_code = runtime_gen.generate_full_runtime()
        run_fn_name = runtime_gen.run_fn
        run_decoded_fn_name = runtime_gen.run_decoded_fn
        decrypt_fn_name = runtime_gen.decrypt_fn

        # Generate helper functions for global variable addresses
        global_var_map = {}
        for info in vm_bytecodes:
            for gname, gtype in info.get('global_vars', {}).items():
                global_var_map.setdefault(gname, gtype)
        global_helpers = ""
        if global_var_map:
            helper_lines = ["// VM Global Address Helpers"]
            for gname, gtype in global_var_map.items():
                safe = ''.join(c if c.isalnum() else '_' for c in gname)
                helper_lines.append(
                    f"static int64_t _vm_gaddr_{safe}(void) {{ return (int64_t)(uintptr_t)&{gname}; }}"
                )
            global_helpers = "\n" + "\n".join(helper_lines) + "\n"

        # Collect VM string literal definitions
        string_literal_map = {}
        for info in vm_bytecodes:
            for name, literal in info.get('string_literals', {}).items():
                string_literal_map.setdefault(name, literal)
        string_literals_code = ""
        if string_literal_map:
            literal_lines = ["// VM String Literals"]
            for name in sorted(string_literal_map):
                literal_lines.append(f"static const char {name}[] = {string_literal_map[name]};")
            string_literals_code = "\n" + "\n".join(literal_lines) + "\n"
        
        # First, replace function bodies using AST positions (before header insertion)
        lines = text_content.split('\n')
        line_offsets = [0]
        for line in lines:
            line_offsets.append(line_offsets[-1] + len(line) + 1)
        
        vm_bytecodes_sorted = sorted(vm_bytecodes, key=lambda x: x['name'], reverse=True)
        
        for vm_info in vm_bytecodes_sorted:
            array_name = vm_info['array_name']
            func_name = vm_info['name']
            return_type = vm_info['return_type']
            is_void = vm_info['is_void']
            func_node = vm_info.get('func_node')
            
            # Extract parameter names from AST for proper argument passing
            param_names = []
            if func_node:
                for child in func_node.get("inner", []):
                    if child.get("kind") == "ParmVarDecl":
                        param_name = child.get("name")
                        if param_name:
                            param_names.append(param_name)
            
            # Generate parameter initialization code
            param_init = ""
            for i, pname in enumerate(param_names):
                param_init += f"    _vm_args[{i}] = (int64_t){pname};\n"
            
            # Find function body by searching for pattern in text
            # Pattern: func_name followed by parentheses and opening brace
            import re
            # Match function_name followed by parameters and opening brace
            pattern = rf'\b{re.escape(func_name)}\s*\([^)]*\)\s*\{{'
            match = re.search(pattern, text_content)
            
            if match:
                # Find the opening brace position
                body_start = match.end() - 1  # Position of '{'
                body_end = find_matching_brace(text_content, body_start)
                
                if body_end > body_start:
                    # Generate VM stub with proper parameter passing
                    argc = len(param_names)
                    decoded_name = f"_vm_decoded_{array_name}"
                    decode_block = (
                        f"    static uint8_t* {decoded_name} = nullptr;\n"
                        f"    if (!{decoded_name}) {{\n"
                        f"        {decoded_name} = (uint8_t*)malloc({array_name}_len);\n"
                        f"        if ({decoded_name}) {{\n"
                        f"            {decrypt_fn_name}({decoded_name}, {array_name}, {array_name}_len, {array_name}_tea_key, {array_name}_tea_nonce);\n"
                        f"        }}\n"
                        f"    }}\n"
                    )
                    if is_void:
                        vm_call = (
                            "{\n"
                            f"    // VM Protected: {func_name}\n"
                            "    int64_t _vm_args[8] = {0};\n"
                            f"{param_init}"
                            f"{decode_block}"
                            f"    if ({decoded_name}) {{\n"
                            f"        {run_decoded_fn_name}({decoded_name}, {array_name}_len, _vm_args, {argc});\n"
                            "    } else {\n"
                            f"        {run_fn_name}({array_name}, {array_name}_len, {array_name}_tea_key, {array_name}_tea_nonce, _vm_args, {argc});\n"
                            "    }\n"
                            "}"
                        )
                    else:
                        vm_call = (
                            "{\n"
                            f"    // VM Protected: {func_name}\n"
                            "    int64_t _vm_args[8] = {0};\n"
                            f"{param_init}"
                            f"{decode_block}"
                            f"    int64_t _vm_result = 0;\n"
                            f"    if ({decoded_name}) {{\n"
                            f"        _vm_result = {run_decoded_fn_name}({decoded_name}, {array_name}_len, _vm_args, {argc});\n"
                            "    } else {\n"
                            f"        _vm_result = {run_fn_name}({array_name}, {array_name}_len, {array_name}_tea_key, {array_name}_tea_nonce, _vm_args, {argc});\n"
                            "    }\n"
                            f"    return ({return_type})_vm_result;\n"
                            "}"
                        )
                    text_content = text_content[:body_start] + vm_call + text_content[body_end+1:]
                    if param_names:
                        print(f"        [VM] Replaced body: {func_name} (params: {', '.join(param_names)})")
                    else:
                        print(f"        [VM] Replaced body: {func_name}")
        
        # Generate bytecode arrays only
        bytecode_arrays = ""
        for info in vm_bytecodes:
            bytecode_arrays += info['array'] + "\n"
        
        # PLT/GOT: Generate global function table initialization (one static array)
        global_plt_code = ""
        if global_plt:
            func_ptrs = ", ".join([f"(_vm_func_ptr_t){fn}" for fn in global_plt])
            # No 'static' keyword to match extern declaration in runtime
            global_plt_code = f"""
// Global PLT - single function table for all VM-protected functions
_vm_func_ptr_t {runtime_gen.func_table_name}[{len(global_plt)}] = {{ {func_ptrs} }};
"""
        
        # Find first #include block (limit search to first 1000 chars to avoid later includes)
        search_region = text_content[:min(1000, len(text_content))]
        include_end = 0
        for m in re.finditer(r'#include\s*[<"][^>"]+[>"]', search_region):
            include_end = max(include_end, m.end())
        
        if include_end > 0:
            nl_pos = text_content.find('\n', include_end)
            if nl_pos != -1:
                # Runtime and bytecodes go after includes
                # PLT goes at END of file (after all function definitions)
                vm_header = ""
                if string_literals_code:
                    vm_header += string_literals_code
                vm_header += "\n// VM Runtime\n" + runtime_code + "\n// VM Bytecodes\n" + bytecode_arrays + "\n"
                text_content = text_content[:nl_pos+1] + vm_header + text_content[nl_pos+1:]
        
        # Append PLT to end of file (all functions are defined by this point)
        if global_helpers or global_plt_code:
            text_content += "\n// VM Global Helpers\n" + global_helpers
        if global_plt_code:
            text_content += "\n// PLT/GOT - Global Function Table (appended at end to resolve forward declarations)\n" + global_plt_code
        
        content = text_content.encode('utf-8')
        with open(file_path, "wb") as f:
            f.write(content)
        return content

    def process_file_text_phase(self, file_path):
        """
        Phase 2: AST-based and safe text-based passes.
        Now uses proper Clang AST for reliable transformations.
        """
        print(f"    Processing (AST/Text) {file_path}...")
        with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Skip generated files that shouldn't be modified
        skip_files = ["graph_wall", "drbg_bytecode", "bytecode", "CMake"]
        if any(skip in file_path for skip in skip_files):
            with open(file_path, "w", encoding='utf-8') as f:
                f.write(content)
            return

        # Only process main source files
        if "bigint.h" in file_path or "src/crypto" in file_path:
            with open(file_path, "w", encoding='utf-8') as f:
                f.write(content)
            return

        # Get AST for this file
        ast = ast_utils.get_ast(file_path)
        
        # ===== AST-BASED PASSES =====
        if ast:
            try:
                # Pass A1: Opaque Predicates (wraps if conditions)
                opaque_pass = OpaquePredicates(probability=0.3)
                content = opaque_pass.apply(content, ast, file_path)
                
                # Write and refresh AST for next pass
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write(content)
                ast = ast_utils.get_ast(file_path)
            except Exception as e:
                print(f"    [!] Opaque Predicates failed: {e}")
        
        if ast:
            try:
                # Pass A2: MBA (Mixed Boolean Arithmetic) - RE-ENABLED
                mba_pass = MBAPass(probability=0.2)
                content = mba_pass.apply(content, ast, file_path)
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write(content)
                ast = ast_utils.get_ast(file_path)
            except Exception as e:
                print(f"    [!] MBA failed: {e}")
        
        if ast:
            try:
                # Pass A3: Instruction Substitution - RE-ENABLED
                insn_pass = InstructionSubstitution(probability=0.2)
                content = insn_pass.apply(content, ast, file_path)
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write(content)
                ast = ast_utils.get_ast(file_path)
            except Exception as e:
                print(f"    [!] Instruction Substitution failed: {e}")
        
        if ast:
            try:
                # Pass A4: Bogus Control Flow (dead code injection)
                bogus_pass = BogusControlFlow(probability=0.2)
                content = bogus_pass.apply(content, ast, file_path)
                
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                print(f"    [!] Bogus Control Flow failed: {e}")
        
        # ===== SAFE TEXT-BASED PASSES =====
        # Pass T1: Constant Encoding (XOR obfuscation of numbers)
        content = const_encoding.ConstantEncoding.apply(content)
        
        # Pass T2: Data Encoding (XOR of array initializers)
        content = advanced.DataEncoding.apply(content)
        
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(content)
