
import random
from .. import ast_utils

class StringEncryption:
    @staticmethod
    def encrypt_strings(content, ast_root, file_path_arg):
        """
        Encrypts string literals using AST to locate them safely.
        Uses OBFUSCATE_KEY with random keys.
        """
        # content is bytes
        nodes = ast_utils.find_nodes(ast_root, "StringLiteral")
        
        edits = []
        for node in nodes:
            if node.get("isImplicit"): continue
            # Check if node belongs to the file we are processing
            if not ast_utils.is_in_file(node, file_path_arg): continue

            s, e = ast_utils.get_source_range(node)
            if s is None or e is None: continue
            if s >= len(content) or e > len(content): continue
            
            text = content[s:e]
            if not text.startswith(b'"'): continue 
            
            # Generate random key
            key = random.randint(1, 255)
            
            from .. import config
            # Extract string value bytes
            s_val_bytes = text[1:-1]
            try:
                s_val = s_val_bytes.decode('utf-8', errors='ignore')
            except:
                continue # Skip weird strings

            seed = random.randint(0, 2**31 - 1)
            # Replacement is a string, needs encoding
            replacement_str = f'{config.MACRO_NAME}("{s_val}", {key}, {seed})'
            replacement = replacement_str.encode('utf-8')
            
            edits.append((s, e, replacement))
            
        edits.sort(key=lambda x: x[0], reverse=True)
        
        last_pos = len(content)
        for s, e, repl in edits:
            if e > last_pos: continue 
            if s >= e: continue
            
            content = content[:s] + repl + content[e:]
            last_pos = s
            
        return content
