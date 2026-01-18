"""
AST-based Mixed Boolean Arithmetic (MBA) pass.
Transforms arithmetic operations into more complex equivalent forms.
"""

import random
import re
from .base import ASTBasePass


class MBAPass(ASTBasePass):
    """
    Applies Mixed Boolean Arithmetic transformations.
    
    Transforms:
    - a + b -> ((a ^ b) + 2 * (a & b))
    - a - b -> ((a ^ b) - 2 * (~a & b))
    - a ^ b -> ((a | b) - (a & b))
    """
    
    def __init__(self, probability=0.4):
        super().__init__(probability)
        self.edited_ranges = []
    
    @staticmethod
    def transform_add(lhs, rhs):
        """Transform a + b"""
        choices = [
            f"(({lhs} ^ {rhs}) + 2 * ({lhs} & {rhs}))",
            f"(({lhs} | {rhs}) + ({lhs} & {rhs}))",
        ]
        return random.choice(choices)
    
    @staticmethod
    def transform_sub(lhs, rhs):
        """Transform a - b"""
        choices = [
            f"(({lhs} ^ {rhs}) - 2 * (~{lhs} & {rhs}))",
            f"({lhs} + ~{rhs} + 1)",
        ]
        return random.choice(choices)
    
    @staticmethod
    def transform_xor(lhs, rhs):
        """Transform a ^ b"""
        return f"(({lhs} | {rhs}) - ({lhs} & {rhs}))"
    
    def overlaps_existing(self, start, end):
        """Check if this edit overlaps with existing edits."""
        for (ex_start, ex_end) in self.edited_ranges:
            if start < ex_end and end > ex_start:
                return True
        return False
    
    def validate_expression_context(self, content, start, end):
        """
        Validate that we're in a valid expression context.
        Returns False if this looks like part of a declaration or invalid location.
        """
        # Check prefix for declaration patterns
        prefix_start = max(0, start - 100)
        prefix = content[prefix_start:start]
        
        # Skip if near function declaration or type declaration
        bad_prefixes = ['void ', 'int ', 'char ', 'bool ', 'static ', 'const ', 
                        'unsigned ', 'signed ', 'struct ', 'class ']
        for bad in bad_prefixes:
            # Check if bad prefix is close and no semicolon/brace between
            idx = prefix.rfind(bad)
            if idx >= 0:
                between = prefix[idx:]
                if ';' not in between and '{' not in between and '}' not in between:
                    return False
        
        return True
    
    def is_safe_to_transform(self, node, content):
        """
        Check if this binary operator is safe to transform.
        Skip pointers, array indexing, type-related operations.
        """
        node_type = node.get("type", {}).get("qualType", "")
        
        # Skip pointer arithmetic
        if "*" in node_type:
            return False
        
        # Skip size types
        if any(t in node_type.lower() for t in ["size_t", "ptrdiff", "pointer", "void"]):
            return False
        
        inner = node.get("inner", [])
        if len(inner) < 2:
            return False
        
        lhs_start, lhs_end = self.get_range(inner[0])
        rhs_start, rhs_end = self.get_range(inner[1])
        
        if lhs_start is None or rhs_start is None:
            return False
        
        # Range validation
        if lhs_start >= len(content) or lhs_end > len(content):
            return False
        if rhs_start >= len(content) or rhs_end > len(content):
            return False
        
        lhs_text = content[lhs_start:lhs_end]
        rhs_text = content[rhs_start:rhs_end]
        
        # Skip unsafe patterns
        unsafe_patterns = ["->", "[", "]", "sizeof", "strlen", "size", "len", 
                          "count", "offset", "static", "void", "()", "\"", "'"]
        for pattern in unsafe_patterns:
            if pattern in lhs_text or pattern in rhs_text:
                return False
        
        # Skip if operands are too long (likely complex expressions)
        if len(lhs_text) > 50 or len(rhs_text) > 50:
            return False
        
        return True
    
    def visit(self, ast, content, file_path):
        """Find BinaryOperator nodes and transform arithmetic."""
        self.edited_ranges = []
        bin_ops = self.find_nodes(ast, "BinaryOperator")
        
        for node in bin_ops:
            if not self.is_in_main_file(node, file_path):
                continue
            
            opcode = node.get("opcode")
            if opcode not in ["+", "-"]:  # Skip ^ to avoid conflicts
                continue
            
            if not self.is_safe_to_transform(node, content):
                continue
            
            if not self.should_transform():
                continue
            
            inner = node.get("inner", [])
            if len(inner) < 2:
                continue
            
            # Get node range
            node_start, node_end = self.get_range(node)
            if node_start is None or node_end is None:
                continue
            
            # Strict range validation
            if node_start >= node_end or node_end - node_start > 100:
                continue
            
            if node_start >= len(content) or node_end > len(content):
                continue
            
            # Validate context
            if not self.validate_expression_context(content, node_start, node_end):
                continue
            
            # Check overlaps
            if self.overlaps_existing(node_start, node_end):
                continue
            
            # Extract operand text
            lhs_start, lhs_end = self.get_range(inner[0])
            rhs_start, rhs_end = self.get_range(inner[1])
            
            if lhs_start is None or rhs_start is None:
                continue
            
            lhs_text = content[lhs_start:lhs_end]
            rhs_text = content[rhs_start:rhs_end]
            
            if not lhs_text.strip() or not rhs_text.strip():
                continue
            
            # Generate replacement
            if opcode == "+":
                replacement = self.transform_add(lhs_text, rhs_text)
            elif opcode == "-":
                replacement = self.transform_sub(lhs_text, rhs_text)
            else:
                continue
            
            self.add_edit(node_start, node_end, replacement)
            self.edited_ranges.append((node_start, node_end))
