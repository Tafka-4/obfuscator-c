"""
AST-based Opaque Predicates pass.
Wraps if conditions with opaque predicates that are always true.
"""

import random
from .base import ASTBasePass


class OpaquePredicates(ASTBasePass):
    """
    Wraps if statement conditions with opaque predicates.
    
    Transforms: if (cond) -> if ((cond) && ((0xAB ^ 0xAB) == 0))
    
    The opaque predicate is always true but hard to analyze statically.
    """
    
    def __init__(self, probability=0.4):
        super().__init__(probability)
        self.edited_ranges = []
    
    @staticmethod
    def gen_opaque_true():
        """Generate an opaque predicate that is always true."""
        a = random.randint(1, 255)
        
        patterns = [
            f"((0x{a:X} ^ 0x{a:X}) == 0)",
            f"(({a} | {a}) == {a})",
            f"((sizeof(int) >= 1))",
            f"((!!(1)) == 1)",
        ]
        return random.choice(patterns)
    
    def overlaps_existing(self, start, end):
        """Check if this edit overlaps with existing edits."""
        for (ex_start, ex_end) in self.edited_ranges:
            if start < ex_end and end > ex_start:
                return True
        return False
    
    def validate_if_context(self, content, cond_start, cond_end):
        """
        Validate that the offset actually points to a valid if condition.
        Returns True only if we can find 'if (' before the condition.
        """
        # Look backwards from cond_start for 'if ('
        search_start = max(0, cond_start - 50)
        prefix = content[search_start:cond_start]
        
        # Must have 'if' followed by optional whitespace and '('
        import re
        if_match = re.search(r'\bif\s*\(\s*$', prefix)
        if not if_match:
            return False
        
        # Check that the condition ends properly (should be followed by ')')
        if cond_end < len(content):
            suffix = content[cond_end:min(len(content), cond_end + 10)]
            if not suffix.lstrip().startswith(')'):
                return False
        
        return True
    
    def visit(self, ast, content, file_path):
        """Find IfStmt nodes and wrap their conditions."""
        self.edited_ranges = []
        if_stmts = self.find_nodes(ast, "IfStmt")
        
        for if_stmt in if_stmts:
            if not self.is_in_main_file(if_stmt, file_path):
                continue
            
            if not self.should_transform():
                continue
            
            inner = if_stmt.get("inner", [])
            if not inner:
                continue
            
            cond_node = inner[0]
            
            # Skip if condition node is not a proper expression
            cond_kind = cond_node.get("kind", "")
            if cond_kind not in ["BinaryOperator", "UnaryOperator", "CallExpr", 
                                  "DeclRefExpr", "IntegerLiteral", "ParenExpr",
                                  "ImplicitCastExpr", "CStyleCastExpr"]:
                continue
            
            cond_start, cond_end = self.get_range(cond_node)
            if cond_start is None or cond_end is None:
                continue
            
            # Basic range validation
            if cond_start >= cond_end or cond_end - cond_start > 200:
                continue
            
            if cond_start >= len(content) or cond_end > len(content):
                continue
            
            # CRITICAL: Validate that this is actually an if condition
            if not self.validate_if_context(content, cond_start, cond_end):
                continue
            
            if self.overlaps_existing(cond_start, cond_end):
                continue
            
            cond_text = content[cond_start:cond_end]
            
            if not cond_text.strip():
                continue
            
            # Skip problematic patterns
            if any(bad in cond_text for bad in ["((", "))", "} ", "{ ", "exit", "return", "static", "void"]):
                continue
            
            opaque = self.gen_opaque_true()
            wrapped = f"(({cond_text}) && {opaque})"
            
            self.add_edit(cond_start, cond_end, wrapped)
            self.edited_ranges.append((cond_start, cond_end))
