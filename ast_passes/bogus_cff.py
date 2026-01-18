"""
AST-based Bogus Control Flow pass.
Inserts fake conditional blocks that never execute.
"""

import random
import string
from .base import ASTBasePass, _rnd_var


class BogusControlFlow(ASTBasePass):
    """
    Inserts bogus (dead) control flow into function bodies.
    
    Techniques:
    - Insert fake if blocks at function start
    - Add dead code with opaque false predicates
    """
    
    def __init__(self, probability=0.3):
        super().__init__(probability)
    
    @staticmethod
    def gen_opaque_false():
        """Generate an opaque predicate that is always false."""
        a = random.randint(1, 255)
        patterns = [
            f"((0x{a:X} ^ 0x{a:X}) != 0)",
            f"((sizeof(int) < 1))",
            f"(((unsigned)(0) > {a}))",
            f"(({a} & {a}) != {a})",
        ]
        return random.choice(patterns)
    
    @staticmethod
    def generate_dead_block():
        """Generate complex dead code that never executes."""
        var = _rnd_var()
        ops = [
            f"volatile int {var} = {random.randint(0, 1000)};",
            f"{var} ^= {random.randint(0, 255)};",
            f"{var} = ({var} << 3) | ({var} >> 5);",
            f"if ({var} > 0) {{ {var}--; }}",
        ]
        random.shuffle(ops)
        return "\n            ".join(ops[:random.randint(2, 3)])
    
    @staticmethod
    def generate_bogus_block():
        """Generate a complete fake if block."""
        dead_code = BogusControlFlow.generate_dead_block()
        opaque = BogusControlFlow.gen_opaque_false()
        return f"""
        if ({opaque}) {{
            {dead_code}
        }}"""
    
    def visit(self, ast, content, file_path):
        """Find function bodies and insert bogus blocks."""
        func_decls = self.find_nodes(ast, "FunctionDecl")
        
        for func in func_decls:
            if not self.is_in_main_file(func, file_path):
                continue
            
            # Skip functions without body
            body = func.get("body")
            if not body:
                continue
            
            if body.get("kind") != "CompoundStmt":
                continue
            
            # Probabilistic application
            if not self.should_transform():
                continue
            
            # Get body range
            body_start, body_end = self.get_range(body)
            if body_start is None:
                continue
            
            # Find the opening brace position
            # We insert right after the opening brace of the function body
            brace_pos = content.find("{", body_start)
            if brace_pos == -1 or brace_pos >= body_end:
                continue
            
            # Generate bogus block
            bogus = self.generate_bogus_block()
            
            # Insert after opening brace
            insert_pos = brace_pos + 1
            self.add_edit(insert_pos, insert_pos, bogus)
