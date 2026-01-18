
import random
import re
from .. import ast_utils

class ControlFlow:
    @staticmethod
    def wrap_opaque_predicates(content):
        """
        Wraps `if (cond) {` with `if ((cond) && (opaque_true)) {`
        Uses balanced parenthesis matching to correctly capture full conditions.
        """
        lines = content.split('\n')
        new_lines = []
        
        for line in lines:
            # Skip lines with strings or comments
            if '"' in line or '//' in line or '#' in line:
                new_lines.append(line)
                continue
            
            # Look for 'if (' pattern
            match = re.search(r'\bif\s*\(', line)
            if match and random.random() < 0.4:
                start = match.end()
                depth = 1
                end = start
                
                # Find matching closing paren
                while end < len(line) and depth > 0:
                    if line[end] == '(':
                        depth += 1
                    elif line[end] == ')':
                        depth -= 1
                    end += 1
                
                if depth == 0:
                    # Successfully found balanced parens
                    cond = line[start:end-1]
                    
                    # Skip if condition is too short or contains problematic chars
                    if len(cond) < 1 or '{' in cond or '}' in cond:
                        new_lines.append(line)
                        continue
                    
                    # Generate opaque true predicate
                    a = random.randint(1, 255)
                    opaque_true = f"((0x{a:02X} ^ 0x{a:02X}) == 0)"
                    
                    # Reconstruct line
                    rest = line[end:]
                    new_cond = f"if (({cond}) && {opaque_true})"
                    line = line[:match.start()] + new_cond + rest
            
            new_lines.append(line)
        
        return '\n'.join(new_lines)


    @staticmethod
    def apply_icff(content, ast_root):
        """
        Applies Indirect Control Flow Flattening to target functions.
        """
        # TODO: Configure targets better. For now use hardcoded list or discover.
        # Actually, let's target any function with enough complexity.
        TARGETS = ["run_server", "handleLogin", "handleClient"]
        
        funcs = ast_utils.find_nodes(ast_root, "FunctionDecl")
        edits = []

        for f in funcs:
            name = f.get("name")
            if name in TARGETS and f.get("body"):
                body = f.get("body")
                if body.get("kind") != "CompoundStmt": continue
                
                start, end = ast_utils.get_source_range(body)
                if start is None or end is None: continue

                stmts = body.get("inner", [])
                if not stmts: continue
                
                # Extract blocks
                blocks = []
                for stmt in stmts:
                    s, e = ast_utils.get_source_range(stmt)
                    if s and e:
                         block_code = content[s:e]
                         blocks.append(block_code)
                
                if len(blocks) < 2: continue 
                
                states = list(range(1, len(blocks) + 2))
                random.shuffle(states)
                
                start_state = states[0]
                end_state = 0
                
                new_body = "{\n    uint32_t _state = " + str(start_state) + ";\n"
                new_body += "    while (_state != 0) {\n"
                # Depend on the NEXT_STATE macro
                new_body += "        switch(NEXT_STATE(_state)) {\n"
                
                for i in range(len(blocks)):
                    current_state = states[i]
                    next_state = states[i+1] if i + 1 < len(blocks) else end_state
                    
                    # Calculate Encrypted Case Label
                    enc_label = ((current_state * 1664525 + 1013904223) & 0xFFFFFFFF)
                    
                    new_body += f"            case {enc_label}: {{\n"
                    new_body += f"                {blocks[i]};\n"
                    new_body += f"                _state = {next_state};\n"
                    if random.random() < 0.3:
                         bogus = random.choice(["OBF_BOGUS_FLOW_LABYRINTH", "OBF_BOGUS_FLOW_GRID", "OBF_BOGUS_FLOW_SCRAMBLE"])
                         new_body += f"                {bogus}\n"
                    new_body += f"                break;\n            }}\n"
                
                # Junk cases
                for _ in range(5):
                    junk_state = random.randint(1000, 9999)
                    if junk_state not in states:
                         enc_junk = ((junk_state * 1664525 + 1013904223) & 0xFFFFFFFF)
                         new_body += f"            case {enc_junk}: {{ _state = {start_state}; break; }}\n"

                new_body += "        }\n    }\n}"
                
                edits.append((start, end, new_body))

        edits.sort(key=lambda x: x[0], reverse=True)
        for s, e, repl in edits:
            content = content[:s] + repl + content[e:]
            
        return content
