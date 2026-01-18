"""
AST-based Instruction Substitution pass.
Transforms common operations into equivalent but less recognizable forms.
"""

import random
from .base import ASTBasePass


class InstructionSubstitution(ASTBasePass):
    """
    Substitutes instructions with semantically equivalent alternatives.
    
    Transforms:
    - x++ -> (x = x + 1)
    - x-- -> (x = x - 1)
    """
    
    def __init__(self, probability=0.4):
        super().__init__(probability)
        self.edited_ranges = []
    
    def overlaps_existing(self, start, end):
        """Check if this edit overlaps with existing edits."""
        for (ex_start, ex_end) in self.edited_ranges:
            if start < ex_end and end > ex_start:
                return True
        return False
    
    def is_safe_unary(self, node, content):
        """Check if unary operator is safe to transform."""
        inner = node.get("inner", [])
        if not inner:
            return False
        
        operand = inner[0]
        start, end = self.get_range(operand)
        if start is None or end is None:
            return False
        
        # Range validation
        if start >= len(content) or end > len(content):
            return False
        
        if start >= end or end - start > 50:
            return False
        
        text = content[start:end]
        
        # Skip member access
        if "->" in text or "." in text:
            return False
        
        # Skip array access
        if "[" in text:
            return False
        
        # Skip complex expressions
        if "(" in text or ")" in text:
            return False
        
        # Only transform simple variable names (alphanumeric + underscore)
        if not text.replace("_", "").isalnum():
            return False
        
        # Skip if too short (likely parsing error)
        if len(text) < 1:
            return False
        
        return True
    
    def visit(self, ast, content, file_path):
        """Transform unary operators only (safer subset)."""
        self.edited_ranges = []
        
        # Transform post-increment/decrement only
        unary_ops = self.find_nodes(ast, "UnaryOperator")
        for node in unary_ops:
            if not self.is_in_main_file(node, file_path):
                continue
            
            opcode = node.get("opcode")
            is_postfix = node.get("isPostfix", False)
            
            if opcode not in ["++", "--"]:
                continue
            
            if not is_postfix:
                continue  # Only transform postfix
            
            if not self.is_safe_unary(node, content):
                continue
            
            if not self.should_transform():
                continue
            
            inner = node.get("inner", [])
            if not inner:
                continue
            
            # Get node range
            node_start, node_end = self.get_range(node)
            if node_start is None or node_end is None:
                continue
            
            # Strict validation
            if node_start >= len(content) or node_end > len(content):
                continue
            
            if node_start >= node_end or node_end - node_start > 60:
                continue
            
            # Check overlaps
            if self.overlaps_existing(node_start, node_end):
                continue
            
            operand = inner[0]
            op_start, op_end = self.get_range(operand)
            if op_start is None:
                continue
            
            var_text = content[op_start:op_end]
            
            if not var_text.strip():
                continue
            
            # Generate replacement
            if opcode == "++":
                replacement = f"({var_text} = {var_text} + 1)"
            else:  # --
                replacement = f"({var_text} = {var_text} - 1)"
            
            self.add_edit(node_start, node_end, replacement)
            self.edited_ranges.append((node_start, node_end))
