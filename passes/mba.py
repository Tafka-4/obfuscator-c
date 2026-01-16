
import random
import re

class MBA:
    @staticmethod
    def generate_expr(op, a, b):
        """
        Returns a string representing a Mixed Boolean Arithmetic expression equivalent to a op b.
        """
        # (a ^ b) + 2 * (a & b) == a + b
        if op == '+':
            choices = [
                f"(({a} ^ {b}) + 2 * ({a} & {b}))",
                f"(({a} | {b}) + ({a} & {b}))"
            ]
            return random.choice(choices)
        
        # (a ^ b) - 2 * (~a & b) == a - b
        elif op == '-':
            choices = [
                f"(({a} ^ {b}) - 2 * (~{a} & {b}))",
                f"({a} + ~{b} + 1)"
            ]
            return random.choice(choices)
            
        # (a | b) - (a & b) == a ^ b
        elif op == '^':
            return f"(({a} | {b}) - ({a} & {b}))"
            
        return f"({a} {op} {b})"

    @staticmethod
    def apply(content):
        """
        Simple regex-based MBA.
        SAFE VERSION: Processes line-by-line and skips lines with strings or comments.
        """
        lines = content.split('\n')
        new_lines = []
        
        # Regex to find simple arithmetic: 'var_or_num + var_or_num'
        pattern = r'(?<!::)(?<!:)(\b[a-zA-Z0-9_]+\b)\s*([\+\-\^])\s*(\b[a-zA-Z0-9_]+\b)(?!\s*(?:(?:\(|::)))'
        
        def replacer(m):
            if random.random() > 0.9: return m.group(0)
            lhs, op, rhs = m.groups()
            return MBA.generate_expr(op, lhs, rhs)

        for line in lines:
            if '"' in line or '//' in line or '#include' in line:
                new_lines.append(line)
                continue
                
            processed = line
            for _ in range(2):
                processed = re.sub(pattern, replacer, processed)
            new_lines.append(processed)
            
        return '\n'.join(new_lines)
