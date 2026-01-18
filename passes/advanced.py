
import random
import re
import string


def _rnd_var():
    """Generate a random cryptic variable name."""
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


class DataEncoding:
    """
    Encodes data arrays and structures by splitting and XOR-encoding.
    
    Techniques:
    1. Split arrays into multiple parts
    2. XOR each part with different keys
    3. Runtime combination to reconstruct original data
    """
    
    @staticmethod
    def split_array_init(elements, var_type="uint8_t"):
        """
        Split an array initialization into multiple encoded parts.
        Returns C++ code that reconstructs the array at runtime.
        """
        if len(elements) < 2:
            return None
        
        # Split into 2-4 parts
        num_parts = min(random.randint(2, 4), len(elements))
        part_size = len(elements) // num_parts
        
        parts = []
        keys = []
        for i in range(num_parts):
            start = i * part_size
            end = start + part_size if i < num_parts - 1 else len(elements)
            key = random.randint(1, 255)
            part_data = [(e ^ key) for e in elements[start:end]]
            parts.append(part_data)
            keys.append(key)
        
        # Generate reconstruction code
        arr_name = _rnd_var()
        code_parts = []
        
        for i, (part, key) in enumerate(zip(parts, keys)):
            part_name = _rnd_var()
            part_str = ", ".join(f"0x{v:02X}" for v in part)
            code_parts.append(f"static {var_type} {part_name}[] = {{{part_str}}};")
        
        return {
            "parts": code_parts,
            "keys": keys,
            "reconstruction": f"// Runtime decode: XOR with keys {keys}"
        }
    
    @staticmethod
    def encode_struct_init(content):
        """
        Encode structure initializations.
        """
        # Pattern for array initializers: {0xXX, 0xYY, ...}
        pattern = r'\{(\s*0x[0-9A-Fa-f]{1,2}\s*(?:,\s*0x[0-9A-Fa-f]{1,2}\s*)+)\}'
        
        def replacer(m):
            if random.random() > 0.5:
                return m.group(0)
            
            try:
                hex_values = re.findall(r'0x([0-9A-Fa-f]{1,2})', m.group(1))
                if len(hex_values) < 4:
                    return m.group(0)
                
                # XOR with random key
                key = random.randint(1, 255)
                encoded = [int(v, 16) ^ key for v in hex_values]
                
                # Generate inline decode (using compound literal)
                encoded_str = ", ".join(f"(uint8_t)(0x{v:02X} ^ 0x{key:02X})" for v in encoded)
                return f"{{{encoded_str}}}"
            except:
                return m.group(0)
        
        return re.sub(pattern, replacer, content)
    
    @staticmethod
    def apply(content):
        """
        Apply data encoding transformations.
        """
        return DataEncoding.encode_struct_init(content)
