"""
Base class for AST-based obfuscation passes.
Provides common functionality for all passes.
"""

import random
import string
from .. import ast_utils


def _rnd_var():
    """Generate a random cryptic variable name."""
    return f"_{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}{''.join(random.choices(string.hexdigits[:16], k=8))}"


class ASTBasePass:
    """
    Base class for AST-based obfuscation passes.
    
    Subclasses should implement:
    - visit(self, ast, content, file_path) - to collect edits
    """
    
    def __init__(self, probability=0.5):
        """
        Initialize pass with transformation probability.
        
        Args:
            probability: Chance (0.0-1.0) to apply transformation to each node
        """
        self.edits = []
        self.probability = probability
    
    def apply(self, content, ast, file_path):
        """
        Apply the pass to content using AST.
        
        Args:
            content: File content as string
            ast: Parsed AST from clang
            file_path: Path to source file
            
        Returns:
            Modified content
        """
        self.edits = []
        self.visit(ast, content, file_path)
        
        # Apply edits in reverse order to preserve offsets
        self.edits.sort(key=lambda x: x[0], reverse=True)
        
        for start, end, replacement in self.edits:
            if start is not None and end is not None:
                content = content[:start] + replacement + content[end:]
        
        return content
    
    def visit(self, ast, content, file_path):
        """
        Visit AST nodes and collect edits.
        Override in subclasses.
        
        Args:
            ast: Parsed AST
            content: File content
            file_path: Path to source file
        """
        raise NotImplementedError("Subclasses must implement visit()")
    
    def add_edit(self, start, end, replacement):
        """Add an edit to the list."""
        if start is not None and end is not None and start < end:
            self.edits.append((start, end, replacement))
    
    def should_transform(self):
        """Returns True if this node should be transformed based on probability."""
        return random.random() < self.probability
    
    def get_node_text(self, node, content):
        """Extract source text for a node."""
        start, end = ast_utils.get_source_range(node)
        if start is not None and end is not None:
            return content[start:end]
        return None
    
    def is_in_main_file(self, node, file_path):
        """Check if node is in the main file (not included)."""
        return ast_utils.is_in_file(node, file_path)
    
    def find_nodes(self, ast, kind):
        """Find all nodes of a specific kind."""
        return ast_utils.find_nodes(ast, kind)
    
    def get_range(self, node):
        """Get source range of a node."""
        return ast_utils.get_source_range(node)
    
    def is_inside_string_or_comment(self, node):
        """
        Check if node might be inside a string literal.
        This is a heuristic - AST nodes shouldn't be inside strings,
        but we check parent context.
        """
        # AST nodes from clang are already outside strings/comments
        # This is one of the key advantages of AST-based approach
        return False
    
    def get_child_nodes(self, node):
        """Get child nodes of a node."""
        return node.get("inner", [])
