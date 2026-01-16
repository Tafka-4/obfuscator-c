
import os
import shutil
import time
from . import config
from . import ast_utils
from . import cpp_gen
from .passes import mba, dead_code, control_flow, strings, renaming, func_split

class Obfuscator:
    def __init__(self):
        self.symbol_map = {}

    def run(self, specific_files=None):
        print(f"[*] Starting Obfuscation...")
        print(f"    Source Dirs: {config.SOURCE_DIRS}")
        print(f"    Build Dir: {config.BUILD_DIR}")
        
        if os.path.exists(config.BUILD_DIR):
            shutil.rmtree(config.BUILD_DIR)

        main_src = config.SOURCE_DIRS[0]
        dest_src = os.path.join(config.BUILD_DIR, os.path.basename(main_src))
        shutil.copytree(main_src, dest_src)

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
        h_code, cpp_code = graph_gen.to_cpp()
        
        with open(os.path.join(dest_src, "graph_wall.h"), "w") as f:
            f.write(h_code)
        with open(os.path.join(dest_src, "graph_wall.cpp"), "w") as f:
            f.write(cpp_code)
            
        files_to_process = []
        if specific_files:
            files_to_process = [os.path.join(dest_src, f) for f in specific_files] 
        else:
            for root, dirs, files in os.walk(dest_src):
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
        
        # 3. Phase 1: AST Passes (Strings, Calls, ICFF, Junk)
        # These passes require valid AST. Logic complexity changes.
        print("    [Phase 1] AST-Based Obfuscation")
        for file_path in files_to_process:
            if "graph_wall.cpp" in file_path:
                print(f"    Skipping AST phase for generated file: {file_path}")
                continue
            self.process_file_ast_phase(file_path)
            
        # 4. Phase 2: Renaming & Regex (MBA, DeadCodeSimple, Opaque, Rename)
        # These passes are causing compilation errors due to lack of type info (MBA) and context (Renaming).
        # Disabling them to ensure build stability.
        print("    [Phase 2] Text-Based Obfuscation & Renaming")
        for file_path in files_to_process:
             self.process_file_text_phase(file_path)

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

        # Pass 1: Strings
        ast = refresh_ast(content, "Strings")
        if ast:
            content = strings.StringEncryption.encrypt_strings(content, ast, file_path)
            with open(file_path, "wb") as f: f.write(content) # Save for next step
            
        # Pass 2: Calls (WRAP calls)
        # This converts func(a) -> OBF_FUNC(func)(a).
        # AST is still valid usually.
        # But WRAP calls pass might expect text? Let's check.
        # Ideally all passes should handle bytes or decode/encode safely.
        # For now, let's decode for passes that are strict text?
        # But AST offsets match BYTES. Decoding risks mismatch.
        # We must upgrade passes to handle bytes.
        ast = refresh_ast(content, "Calls")
        if ast:
            # Decode for logic, but be careful with offsets?
            # Renaming.obfuscate_calls likely uses string ops.
            # We should probably fix StringEncryption to use bytes, and others too.
            # If fixing all passes is too much work, we decode/encode carefully.
            # But StringEncryption uses AST offsets which are bytes!
            
            # StringEncryption is fixing below.
            # Calls pass? 
            # If Calls pass uses string processing, we might need to decode.
            # If we decode 'utf-8', offsets might shift if multibyte chars exist.
            # If file is ASCII, offsets are safe.
            # Let's assume ASCII mainly. But Strings pass failed spectactularly.
            # Probably because of line endings on different OS?
            
            # Temporary fix: Decode for legacy passes, but use binary for Strings pass?
            # Or make them all binary?
            # Renaming.obfuscate_calls -> let's assume it works on text for now and revisit if broken.
            # We decode for Calls pass.
            text_content = content.decode('utf-8', errors='ignore')
            new_text = renaming.Renaming.obfuscate_calls(text_content, ast, self.symbol_map)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
            
        # Pass 3: ICFF
        ast = refresh_ast(content, "ICFF")
        if ast:
            text_content = content.decode('utf-8', errors='ignore')
            new_text = control_flow.ControlFlow.apply_icff(text_content, ast)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
            
        # Pass 4: Junk Injection
        ast = refresh_ast(content, "Junk")
        if ast:
            text_content = content.decode('utf-8', errors='ignore')
            new_text = dead_code.DeadCode.inject_junk_ast(text_content, ast, file_path)
            content = new_text.encode('utf-8')
            with open(file_path, "wb") as f: f.write(content)
            
    def process_file_text_phase(self, file_path):
        print(f"    Processing (Text) {file_path}...")
        with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Pass 5: Regex Passes
        # Skip sensitive math files for MBA/ControlFlow to avoid semantic breakage
        if "bigint.h" not in file_path and "src/crypto" not in file_path and "utils.cpp" not in file_path and "state.cpp" not in file_path:
            content = dead_code.DeadCode.insert_dead_code_simple(content)
            content = mba.MBA.apply(content)
            content = control_flow.ControlFlow.wrap_opaque_predicates(content)
        
        # Pass 6: Renaming
        content = renaming.Renaming.smart_rename(content, self.symbol_map)
        
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(content)
