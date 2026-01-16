
import random
import string

class JunkFactory:
    """
    Generates realistic-looking C++ junk code.
    Uses S-Box access, math operations, and loops to look 'organic'.
    """
    
    @staticmethod
    def generate_body(depth=0, available_vars=None):
        # Top-level call initializes variables
        if available_vars is None:
            available_vars = []
            # Generate top-level declarations
            decls = []
            for _ in range(random.randint(5, 10)):
                v = "_v" + JunkFactory.random_suffix()
                available_vars.append(v)
                val = random.randint(0, 1000)
                decls.append(f"volatile int {v} = {val};")
            
            # Generate statements using these vars
            stmts_block = JunkFactory.generate_stmts(available_vars, depth=0)
            return "\n".join(decls) + "\n" + stmts_block
        else:
            # Recursive call (should use generate_stmts really, but keep compat)
            return JunkFactory.generate_stmts(available_vars, depth)

    @staticmethod
    def generate_stmts(available_vars, depth):
        if depth > 2:
            return JunkFactory.gen_simple_math(available_vars)
            
        stmts = []
        num_stmts = random.randint(3, 8)
        
        for _ in range(num_stmts):
            choice = random.choice(["math", "control", "sbox", "string"])
            if choice == "math":
                stmts.append(JunkFactory.gen_simple_math(available_vars))
            elif choice == "control":
                stmts.append(JunkFactory.gen_control_flow(depth, available_vars))
            elif choice == "sbox":
                stmts.append(JunkFactory.gen_sbox_access(available_vars))
            elif choice == "string":
                 stmts.append(JunkFactory.gen_string_op())
                 
        return "\n".join(stmts)

    @staticmethod
    def gen_simple_math(available_vars):
        if not available_vars: return ""
        v = random.choice(available_vars)
        op_type = random.randint(0, 3)
        if op_type == 0:
             return f"{v} += {random.randint(1,100)};"
        elif op_type == 1:
             return f"{v} ^= {random.randint(1,255)};"
        elif op_type == 2:
             return f"{v} = ({v} * 3) + 1;"
        else:
             return f"{v} = ({v} >> 2) | ({v} << 6);"

    @staticmethod
    def gen_sbox_access(available_vars):
        if not available_vars: return ""
        v = random.choice(available_vars)
        idx = random.randint(0, 255)
        from .. import config
        return f"{v} ^= {config.NS_NAME}::{config.SBOX_NAME}[{idx}];" # XOR existing var with SBOX

    @staticmethod
    def gen_control_flow(depth, available_vars):
        v = "_c" + JunkFactory.random_suffix()
        body = JunkFactory.generate_stmts(available_vars, depth + 1)
        
        if random.random() < 0.5:
            return f"""
            volatile int {v} = {random.randint(0, 10)};
            if ({v} > 5) {{
                {body}
            }}
            """
        else:
             return f"""
             for(int {v}=0; {v} < {random.randint(2,5)}; ++{v}) {{
                 {body}
             }}
             """

    @staticmethod
    def gen_string_op():
        # Decoy string usage
        # We assume OBFUSCATE_KEY macro is available
        decoy = "".join(random.choices(string.ascii_letters, k=8))
        key = random.randint(1, 255)
        # We assume result is unused, just side effect of hydration or whatever
        v = "_str" + JunkFactory.random_suffix()
        from .. import config
        seed = random.randint(0, 2**31 - 1)
        return f"const char* {v} = {config.MACRO_NAME}(\"{decoy}\", {key}, {seed});"

    @staticmethod
    def random_suffix():
        return "".join(random.choices("0123456789ABCDEF", k=4))
