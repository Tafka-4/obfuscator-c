"""
Struct Layout Analyzer for VM Bytecode Compiler

Parses Clang AST to extract struct definitions and compute member offsets.
This enables proper compilation of struct member access (ptr->member).
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class FieldInfo:
    """Information about a struct field."""
    name: str
    type_name: str
    size: int  # in bytes
    offset: int  # offset from struct start


@dataclass
class StructLayout:
    """Complete layout information for a struct."""
    name: str
    fields: List[FieldInfo]
    total_size: int
    alignment: int = 1
    
    def get_field_offset(self, field_name: str) -> Optional[int]:
        """Get offset for a named field."""
        for field in self.fields:
            if field.name == field_name:
                return field.offset
        return None
    
    def get_field_size(self, field_name: str) -> Optional[int]:
        """Get size for a named field."""
        for field in self.fields:
            if field.name == field_name:
                return field.size
        return None


class StructLayoutAnalyzer:
    """
    Analyzes Clang AST to extract struct layouts with member offsets.
    
    Usage:
        analyzer = StructLayoutAnalyzer()
        layouts = analyzer.analyze(ast)
        offset = layouts['MyStruct'].get_field_offset('member')
    """
    
    # Type sizes for C/C++ (64-bit platform)
    TYPE_SIZES = {
        'char': 1, 'signed char': 1, 'unsigned char': 1,
        'short': 2, 'unsigned short': 2,
        'int': 4, 'unsigned int': 4,
        'long': 8, 'unsigned long': 8,
        'long long': 8, 'unsigned long long': 8,
        'float': 4, 'double': 8,
        'void *': 8, 'char *': 8, 'int *': 8,
        'int8_t': 1, 'uint8_t': 1,
        'int16_t': 2, 'uint16_t': 2,
        'int32_t': 4, 'uint32_t': 4,
        'int64_t': 8, 'uint64_t': 8,
        'size_t': 8, 'ssize_t': 8,
        'bool': 1, '_Bool': 1,
    }
    
    # Default alignment for types
    TYPE_ALIGNMENTS = {
        1: 1, 2: 2, 4: 4, 8: 8
    }
    
    def __init__(self):
        self.structs: Dict[str, StructLayout] = {}
        self.typedef_map: Dict[str, str] = {}  # typedef name -> actual type
    
    def analyze(self, ast: Dict) -> Dict[str, StructLayout]:
        """
        Analyze AST and extract all struct layouts.
        
        Args:
            ast: Clang AST as dictionary
            
        Returns:
            Dict mapping struct names to StructLayout
        """
        self.structs = {}
        self.typedef_map = {}
        
        # First pass: collect typedefs
        self._collect_typedefs(ast)
        
        # Second pass: analyze struct definitions
        self._analyze_node(ast)
        
        return self.structs
    
    def _collect_typedefs(self, node: Dict):
        """Collect typedef mappings for anonymous structs."""
        if node.get("kind") == "TypedefDecl":
            typedef_name = node.get("name", "")
            inner = node.get("inner", [])
            
            # Check for typedef struct { ... } Name pattern
            for child in inner:
                # Handle ElaboratedType wrapping RecordType or direct RecordDecl
                if child.get("kind") == "ElaboratedType":
                    owned = child.get("ownedTagDecl", {})
                    if owned.get("kind") in ("RecordDecl", "CXXRecordDecl"):
                        # Anonymous struct - map typedef name to struct ID
                        struct_id = owned.get("id", "")
                        if struct_id:
                            self.typedef_map[struct_id] = typedef_name
                elif child.get("kind") == "RecordType":
                    # Direct RecordType reference
                    decl = child.get("decl", {})
                    struct_id = decl.get("id", "")
                    if struct_id:
                        self.typedef_map[struct_id] = typedef_name
        
        # Recurse
        for child in node.get("inner", []):
            self._collect_typedefs(child)
    
    def _analyze_node(self, node: Dict):
        """Recursively analyze AST nodes for struct definitions."""
        kind = node.get("kind", "")
        
        if kind in ("RecordDecl", "CXXRecordDecl"):
            self._analyze_record_decl(node)
        
        # Recurse into children
        for child in node.get("inner", []):
            self._analyze_node(child)
    
    def _analyze_record_decl(self, node: Dict):
        """Analyze a RecordDecl (struct definition)."""
        # Skip incomplete declarations
        if not node.get("completeDefinition", False):
            return
        
        # Get struct name
        struct_name = node.get("name", "")
        node_id = node.get("id", "")
        
        # Handle anonymous structs within typedefs
        if not struct_name and node_id:
            # Look up typedef name by struct ID
            if node_id in self.typedef_map:
                struct_name = self.typedef_map[node_id]
        
        if not struct_name:
            return  # Skip anonymous structs we can't identify
        
        # Extract fields
        fields: List[FieldInfo] = []
        current_offset = 0
        max_alignment = 1
        
        for child in node.get("inner", []):
            if child.get("kind") == "FieldDecl":
                field_name = child.get("name", "")
                field_type = child.get("type", {}).get("qualType", "")
                
                # Get field size/alignment
                field_size = self._get_type_size(field_type)
                alignment = self._get_type_alignment(field_type)
                
                # Apply alignment
                if alignment > 0:
                    current_offset = self._align(current_offset, alignment)
                
                fields.append(FieldInfo(
                    name=field_name,
                    type_name=field_type,
                    size=field_size,
                    offset=current_offset
                ))
                
                current_offset += field_size
                if alignment > max_alignment:
                    max_alignment = alignment
        
        # Total struct size (with final padding)
        if fields:
            total_size = self._align(current_offset, max_alignment)
        else:
            total_size = 0
        
        self.structs[struct_name] = StructLayout(
            name=struct_name,
            fields=fields,
            total_size=total_size,
            alignment=max_alignment
        )
        
        # Also map typedef aliases
        for typedef_name, mapped in self.typedef_map.items():
            if mapped == struct_name:
                self.structs[typedef_name] = self.structs[struct_name]
    
    def _get_type_size(self, type_name: str) -> int:
        """Get size of a type in bytes."""
        clean_type = self._clean_type_name(type_name)
        
        # Check if pointer type
        if '*' in clean_type:
            return 8  # 64-bit pointer
        
        # Check if array type
        if '[' in clean_type:
            # Extract element type and count
            base_type = clean_type.split('[')[0].strip()
            try:
                count = int(clean_type.split('[')[1].split(']')[0])
            except:
                count = 1
            return self._get_type_size(base_type) * count
        
        # Check known types
        if clean_type in self.TYPE_SIZES:
            return self.TYPE_SIZES[clean_type]
        
        # Check if it's a known struct
        if clean_type in self.structs:
            return self.structs[clean_type].total_size
        
        # Default to pointer size for unknown types
        return 8

    def _get_type_alignment(self, type_name: str) -> int:
        """Get alignment of a type in bytes."""
        clean_type = self._clean_type_name(type_name)
        
        # Pointer types align to pointer size
        if '*' in clean_type:
            return 8
        
        # Array types align to their element type
        if '[' in clean_type:
            base_type = clean_type.split('[')[0].strip()
            return self._get_type_alignment(base_type)
        
        # Known scalar types
        if clean_type in self.TYPE_SIZES:
            size = self.TYPE_SIZES[clean_type]
            return self.TYPE_ALIGNMENTS.get(size, min(size, 8))
        
        # Known struct types
        if clean_type in self.structs:
            return self.structs[clean_type].alignment or min(self.structs[clean_type].total_size, 8)
        
        # Default to pointer alignment for unknown types
        return 8

    def _clean_type_name(self, type_name: str) -> str:
        """Normalize a type name for lookup."""
        clean_type = type_name.strip()
        for qual in ['const ', 'volatile ', 'restrict ']:
            clean_type = clean_type.replace(qual, '')
        clean_type = clean_type.replace('struct ', '').replace('class ', '')
        return clean_type.strip()
    
    def _align(self, offset: int, alignment: int) -> int:
        """Align offset to given alignment."""
        if alignment <= 0:
            return offset
        remainder = offset % alignment
        if remainder == 0:
            return offset
        return offset + (alignment - remainder)
    
    def get_offset(self, struct_name: str, field_name: str) -> Optional[int]:
        """
        Get the offset of a field within a struct.
        
        Args:
            struct_name: Name of the struct type
            field_name: Name of the field
            
        Returns:
            Offset in bytes, or None if not found
        """
        # Try direct lookup
        if struct_name in self.structs:
            return self.structs[struct_name].get_field_offset(field_name)
        
        # Try without 'struct ' prefix
        clean_name = struct_name.replace('struct ', '')
        if clean_name in self.structs:
            return self.structs[clean_name].get_field_offset(field_name)
        
        return None
    
    def debug_print(self):
        """Print all analyzed structs for debugging."""
        for name, layout in self.structs.items():
            print(f"struct {name} ({layout.total_size} bytes):")
            for field in layout.fields:
                print(f"  +{field.offset:3d}: {field.name} ({field.type_name}, {field.size} bytes)")
