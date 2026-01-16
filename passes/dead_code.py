
import random
from .. import ast_utils
from .mba import MBA

def random_hex(length=8):
    return "_" + ''.join(random.choices("0123456789ABCDEF", k=length))

class DeadCode:
    @staticmethod
    def generate_junk_code():
        """
        Generates a block of C++ junk code.
        """
        var_name = "junk_" + random_hex(8)
        ops = ['+', '-', '^'] # MBA supported ops
        val = random.randint(0, 1000)
        
        code = f"    // Junk Start\n"
        code += f"    volatile int {var_name} = {val};\n"
        code += f"    if ({var_name} < {val + 100}) {{\n"
        for _ in range(random.randint(2, 5)):
            op = random.choice(ops)
            operand = random.randint(1, 100)
            expr = MBA.generate_expr(op, var_name, str(operand))
            code += f"        {var_name} = {expr};\n"
        code += f"    }}\n"
        code += f"    // Junk End\n"
        return code

    @staticmethod
    def generate_dummy_function():
        """
        Generates a random C++ function with complex junk logic.
        """
        name = "dummy_" + random_hex(6)
        code = f"static void {name}() {{\n"
        code += "    volatile int state = 0;\n"
        code += "    while (state < 10) {\n"
        code += "        switch(state) {\n"
        for i in range(10):
            code += f"            case {i}: \n"
            code += f"                state += {random.randint(1,3)};\n"
            code += f"                break;\n"
        code += "        }\n"
        code += "    }\n"
        code += "}\n"
        return code, name

    @staticmethod
    def insert_dead_code_simple(content):
        """
        Injects junk code at the beginning of function bodies (Regex based).
        """
        lines = content.split('\n')
        new_lines = []
        
        for line in lines:
            new_lines.append(line)
            stripped = line.strip()
            if stripped.endswith('{') and ')' in stripped and not stripped.startswith("if") and not stripped.startswith("for") and not stripped.startswith("while") and not stripped.startswith("switch"):
                if random.random() < 0.3:
                    new_lines.append(DeadCode.generate_junk_code())
                    
        return '\n'.join(new_lines)

    @staticmethod
    def inject_junk_ast(content, ast_root, file_path=""):
        """
        Injects junk code into Function Bodies using AST.
        """
        if file_path.endswith(".h") or file_path.endswith(".hpp"):
            return content
            
        insertion_points = []
        funcs = ast_utils.find_nodes(ast_root, "FunctionDecl")
        
        for f in funcs:
            body = f.get("body")
            if not body or body.get("kind") != "CompoundStmt":
                continue
                
            start_off, _ = ast_utils.get_source_range(body)
            if start_off is not None:
                if start_off < len(content) and content[start_off] == '{':
                    insertion_points.append(start_off + 1)

        insertion_points.sort(reverse=True)
        unique_points = []
        if insertion_points:
            unique_points.append(insertion_points[0])
            for p in insertion_points[1:]:
                if p != unique_points[-1]:
                    unique_points.append(p)
        
        for offset in unique_points:
            if random.random() < 0.5:
                junk = "\n" + DeadCode.generate_junk_code()
                content = content[:offset] + junk + content[offset:]
                
        return content
