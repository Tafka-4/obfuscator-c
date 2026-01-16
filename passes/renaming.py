
import random
import re
from .. import ast_utils
from .. import config

def random_hex(length=8):
    return "_" + ''.join(random.choices("0123456789ABCDEF", k=length))

class Renaming:
    @staticmethod
    def find_all_declarations(ast_root, file_content, file_path="", existing_symbols=None):
        """
        Scans AST for all FunctionDecl and VarDecl to rename.
        Returns a dictionary of {original_name: new_name}.
        """
        symbols = {}
        if existing_symbols:
            # We don't copy, just use values for collision check
            used_values = set(existing_symbols.values())
        else:
            used_values = set()
        
        funcs = ast_utils.find_nodes(ast_root, "FunctionDecl")
        funcs += ast_utils.find_nodes(ast_root, "CXXMethodDecl")
        vars_ = ast_utils.find_nodes(ast_root, "VarDecl")
        structs = ast_utils.find_nodes(ast_root, "RecordDecl")
        structs += ast_utils.find_nodes(ast_root, "CXXRecordDecl")
        fields = ast_utils.find_nodes(ast_root, "FieldDecl")
        
        all_decls = funcs + vars_ + structs + fields
        
        for decl in all_decls:
            name = decl.get("name")
            if decl.get("isImplicit"): continue
            if ast_utils.is_safe(name, decl, file_path):
                if name in existing_symbols:
                    pass # Already renamed globally
                elif name not in symbols:
                    while True:
                        new_name = random_hex(8)
                        if new_name not in used_values and new_name not in symbols.values():
                            symbols[name] = new_name
                            used_values.add(new_name)
                            break
            else:
                 pass
                 
        return symbols

    @staticmethod
    def smart_rename(content, symbol_map):
        """
        Renames symbols in content using a tokenizer approach.
        """
        if not symbol_map: return content
        
        def repl(match):
            s = match.group(0)
            if s.startswith('/'): return s # Comment
            if s.startswith('"'): return s # String
            if s.startswith('\''): return s # Char literal
            return symbol_map.get(s, s) 
        
        pattern = r'''(//[^\n]*|/\*[\s\S]*?\*/|#\s*include\s*[<"][^">]+[">]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b[a-zA-Z_]\w*\b)'''
        return re.sub(pattern, repl, content)

    @staticmethod
    def obfuscate_calls(content, ast_root, symbol_map):
        """
        Wraps function calls to target symbols with OBF_FUNC macro.
        """
        edits = [] 
        
        calls = ast_utils.find_nodes(ast_root, "CallExpr")
        for call in calls:
            inner = call.get("inner", [])
            if not inner: continue
            
            callee_node = inner[0]
            
            while callee_node.get("kind") == "ImplicitCastExpr" or callee_node.get("kind") == "CStyleCastExpr":
                 callee_inner = callee_node.get("inner", [])
                 if callee_inner:
                     callee_node = callee_inner[0]
                 else:
                     break
            
            if callee_node.get("kind") == "DeclRefExpr":
                decl = callee_node.get("referencedDecl", {})
                name = decl.get("name")
                kind = decl.get("kind")
                if kind == "CXXMethodDecl": continue # Don't wrap member calls
                
                if name == "is_prime": continue 
                if name in symbol_map:
                    start, end = ast_utils.get_source_range(callee_node)
                    if start is not None and end is not None:
                         # Verify name presence
                         if content[start:start+len(name)] == name:
                             edits.append((start, start+len(name), f"OBF_FUNC({name})"))

        edits.sort(key=lambda x: x[0], reverse=True)
        
        for start, end, repl in edits:
            content = content[:start] + repl + content[end:]
            
        return content
