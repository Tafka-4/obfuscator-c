
import random
import re


class ConstantEncoding:
    """
    Encodes numeric constants using various transformations to hide their true values.
    
    Techniques:
    1. XOR encoding: x → (a ^ b) where a ^ b = x
    2. ADD/SUB encoding: x → (a + b) or (a - b)
    3. Polynomial encoding: x → (a * b + c)
    4. NOT/NEG encoding: x → ~(~x) or -(-x)
    5. Mixed: combination of above
    """
    
    @staticmethod
    def generate_xor_pair(value):
        """Generate two POSITIVE values that XOR to the target value."""
        # Ensure value is treated as unsigned 32-bit
        value = value & 0xFFFFFFFF
        # Generate mask in the same bit range as value to avoid negative XOR results
        if value == 0:
            mask = random.randint(1, 0xFFFF)
            return mask, mask  # a ^ a = 0
        max_bits = min(value.bit_length() + 4, 32)
        max_mask = (1 << max_bits) - 1
        mask = random.randint(1, max_mask)
        result = value ^ mask
        # Ensure both are positive (valid hex)
        mask = mask & 0xFFFFFFFF
        result = result & 0xFFFFFFFF
        return mask, result
    
    @staticmethod
    def generate_add_pair(value):
        """Generate two values that add to the target value."""
        a = random.randint(0, abs(value) + 1000)
        b = value - a
        return a, b
    
    @staticmethod
    def generate_sub_pair(value):
        """Generate two values where a - b = value."""
        b = random.randint(0, 1000)
        a = value + b
        return a, b
    
    @staticmethod
    def generate_mul_add(value):
        """Generate a * b + c = value (for small values)."""
        if value == 0:
            return 0, 1, 0
        factors = []
        for i in range(2, min(abs(value), 100)):
            if value % i == 0:
                factors.append(i)
        if not factors:
            # Fall back to simple case: 1 * value + 0
            return 1, value, 0
        a = random.choice(factors)
        b = value // a
        c = random.randint(-100, 100)
        # Adjust b to account for c
        return a, b - c // a if c % a == 0 else b, value - a * b
    
    @staticmethod
    def encode_constant(value, depth=1):
        """
        Generate an encoded expression for the constant value.
        depth controls recursion for nested encoding.
        """
        if depth <= 0 or random.random() < 0.3:
            return str(value)
        
        # Ensure value is valid for encoding
        if value < 0:
            return str(value)
        
        # Choose encoding method
        method = random.choice(['xor', 'add', 'sub', 'not', 'shift'])
        
        if method == 'xor':
            a, b = ConstantEncoding.generate_xor_pair(value)
            # Use hex only for positive values within 32-bit
            if a >= 0 and b >= 0 and a <= 0xFFFFFFFF and b <= 0xFFFFFFFF:
                return f"(0x{a:X} ^ 0x{b:X})"
            else:
                return str(value)
        
        elif method == 'add':
            a, b = ConstantEncoding.generate_add_pair(value)
            return f"({a} + ({b}))"
        
        elif method == 'sub':
            a, b = ConstantEncoding.generate_sub_pair(value)
            return f"({a} - {b})"
        
        elif method == 'not':
            # ~(~x) = x
            return f"(~(~{value}))"
        
        elif method == 'shift':
            # For values that are powers of 2 or can be expressed with shifts
            if value > 0 and (value & (value - 1)) == 0:
                # Power of 2
                shift = value.bit_length() - 1
                return f"(1 << {shift})"
            else:
                # x = (x >> n) << n + (x & ((1 << n) - 1))
                n = random.randint(1, 4)
                high = value >> n
                low = value & ((1 << n) - 1)
                if high > 0:
                    return f"(({high} << {n}) | {low})"
                return str(value)
        
        return str(value)
    
    @staticmethod
    def apply(content):
        """
        Apply constant encoding to numeric literals in the content.
        SAFE VERSION: Processes line-by-line and skips problematic lines.
        """
        lines = content.split('\n')
        new_lines = []
        
        # Pattern to match integer literals (decimal and hex)
        # Avoid matching in strings, comments, includes, array sizes, etc.
        decimal_pattern = r'(?<![a-zA-Z0-9_.\"\'])(\b(?:0|[1-9][0-9]*)\b)(?![a-zA-Z0-9_\"\'\[])'
        hex_pattern = r'(?<![a-zA-Z0-9_.\"\'])(0x[0-9A-Fa-f]+)(?![a-zA-Z0-9_\"\'])'
        
        for line in lines:
            # Skip lines with strings, comments, includes, defines, array declarations
            if any(skip in line for skip in ['"', '//', '#include', '#define', '#pragma', '[]', 'case ', 'sizeof']):
                new_lines.append(line)
                continue
            
            # Skip lines that look like they're part of array initialization
            if re.search(r'\[\s*\d+\s*\]', line):
                new_lines.append(line)
                continue
            
            processed = line
            
            def replace_hex(m):
                if random.random() > 0.7:  # Only encode 70% of constants
                    return m.group(0)
                try:
                    val = int(m.group(1), 16)
                    if val == 0 or val > 0xFFFFFFFF:
                        return m.group(0)
                    return ConstantEncoding.encode_constant(val, depth=random.randint(1, 2))
                except:
                    return m.group(0)
            
            def replace_decimal(m):
                if random.random() > 0.7:  # Only encode 70% of constants
                    return m.group(0)
                try:
                    val = int(m.group(1))
                    # Skip small values (likely loop counters, indices)
                    if val <= 10 or val > 0xFFFFFFFF:
                        return m.group(0)
                    return ConstantEncoding.encode_constant(val, depth=random.randint(1, 2))
                except:
                    return m.group(0)
            
            # Apply hex pattern first
            processed = re.sub(hex_pattern, replace_hex, processed)
            # Then decimal
            processed = re.sub(decimal_pattern, replace_decimal, processed)
            
            new_lines.append(processed)
        
        return '\n'.join(new_lines)
