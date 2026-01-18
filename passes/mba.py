
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
        SAFE VERSION: Processes line-by-line and skips lines with strings, comments,
        type declarations, struct definitions, and pointer declarations.
        """
        lines = content.split('\n')
        new_lines = []
        
        # Regex to find simple arithmetic: 'var_or_num + var_or_num'
        pattern = r'(?<!::)(?<!:)(\b[a-zA-Z0-9_]+\b)\s*([\+\-\^])\s*(\b[a-zA-Z0-9_]+\b)(?!\s*(?:(?:\(|::)))'
        
        # Keywords that indicate type declarations - skip these lines
        TYPE_KEYWORDS = (
            'struct', 'class', 'typedef', 'enum', 'union',
            'int8_t', 'int16_t', 'int32_t', 'int64_t',
            'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
            'size_t', 'ssize_t', 'ptrdiff_t',
            'char', 'short', 'int', 'long', 'float', 'double',
            'unsigned', 'signed', 'void', 'bool',
            'const', 'volatile', 'static', 'extern',
        )
        
        def should_skip_line(line):
            """Check if line should be skipped."""
            stripped = line.strip()
            
            # Skip empty, comments, includes, strings
            if not stripped or stripped.startswith('//') or stripped.startswith('#'):
                return True
            if '"' in line or "'" in line:
                return True
            
            # Skip return/break/continue/case statements
            if stripped.startswith('return ') or stripped.startswith('break') or \
               stripped.startswith('continue') or stripped.startswith('case '):
                return True
            
            # Skip struct/class definitions
            if 'struct ' in line or 'class ' in line or 'typedef ' in line:
                return True
            
            # Skip lines that look like variable/member declarations
            # Pattern: type* name; or type name; at start of line
            if stripped.endswith(';'):
                for kw in TYPE_KEYWORDS:
                    if kw in line and '*' not in stripped.split('=')[0].split('(')[0]:
                        # Likely a declaration without assignment
                        if '=' not in line and '(' not in line:
                            return True
            
            # Skip lines with pointer type declarations (type* var)
            if re.search(r'\b(u?int\d+_t|char|void|size_t)\s*\*', line):
                return True
            
            # Skip array declarations and sizeof
            if 'sizeof' in line or re.search(r'\[[^\]]*\]', line):
                return True
            
            # Skip function signatures (return types before function names)
            if re.match(r'^\s*(static\s+)?(inline\s+)?(const\s+)?\w+[\*\s]+\w+\s*\(', stripped):
                return True
            
            return False
        
        def replacer(m):
            if random.random() > 0.5:  # Reduced probability for safety
                return m.group(0)
            lhs, op, rhs = m.groups()
            
            # Don't transform if either operand looks like a type/size
            skip_terms = ('size', 'len', 'count', 'offset', 'ptr', 'buf', 'sizeof')
            for term in skip_terms:
                if term in lhs.lower() or term in rhs.lower():
                    return m.group(0)
            
            return MBA.generate_expr(op, lhs, rhs)

        for line in lines:
            if should_skip_line(line):
                new_lines.append(line)
                continue
                
            processed = line
            # Only one pass instead of two
            processed = re.sub(pattern, replacer, processed)
            new_lines.append(processed)
            
        return '\n'.join(new_lines)
