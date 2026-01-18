"""
Graph-based function splitting pass.
Splits marked functions into sequential fragments connected via branchy paths.
"""

import os
import random
import string
from .base import ASTBasePass
from .. import ast_utils


def _rnd_suffix(n=6):
    return "".join(random.choices("0123456789abcdef", k=n))


class GraphSplit(ASTBasePass):
    """
    Splits functions annotated with // GRAPH_SPLIT into fragments and
    connects them through graph wall node calls with true/false branches.
    """

    def __init__(self, graph_nodes=None, min_frags=2, max_frags=4,
                 auto_mode=True, min_stmt_count=6):
        super().__init__(probability=1.0)
        self.graph_nodes = list(graph_nodes or [])
        self.min_frags = min_frags
        self.max_frags = max_frags
        self.auto_mode = auto_mode
        self.min_stmt_count = min_stmt_count

    def _has_marker(self, content, func_node):
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        loc = func_node.get("loc", {})
        line = loc.get("line", 0)
        if not line:
            return False
        lines = content.split("\n")
        start = max(0, line - 5)
        for idx in range(start, line - 1):
            if idx < len(lines) and "// GRAPH_SPLIT" in lines[idx]:
                return True
        return False

    def _has_vm_marker(self, content, func_node):
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        loc = func_node.get("loc", {})
        line = loc.get("line", 0)
        if not line:
            return False
        lines = content.split("\n")
        start = max(0, line - 5)
        for idx in range(start, line - 1):
            if idx < len(lines) and "// VM_PROTECT" in lines[idx]:
                return True
        return False

    def _is_in_target_file(self, node, file_path):
        if ast_utils.is_in_file(node, file_path):
            return True
        loc = node.get("loc") or node.get("range", {}).get("begin") or {}
        if loc.get("includedFrom"):
            return False
        if loc.get("file"):
            return os.path.abspath(loc.get("file")) == os.path.abspath(file_path)
        return loc.get("offset") is not None

    def _auto_candidate(self, func_node, stmt_count):
        if not self.auto_mode:
            return False
        if stmt_count < self.min_stmt_count:
            return False
        if func_node.get("isImplicit"):
            return False
        name = func_node.get("name") or ""
        if name in ("main",):
            return False
        if func_node.get("isInline"):
            return False
        return True

    def _extend_stmt_end(self, start, end, content_bytes):
        if end is None or end >= len(content_bytes):
            return end
        i = end
        while i < len(content_bytes) and content_bytes[i] in b" \t\r\n":
            i += 1
        if i < len(content_bytes) and content_bytes[i:i+1] == b";":
            return i + 1
        return end

    def _normalize_indent(self, block, indent):
        if isinstance(block, bytes):
            return self._normalize_indent_bytes(block, indent)
        lines = block.splitlines()
        non_empty = [ln for ln in lines if ln.strip()]
        if not non_empty:
            return ""
        min_ws = min(len(ln) - len(ln.lstrip(" ")) for ln in non_empty)
        trimmed = [ln[min_ws:] if len(ln) >= min_ws else ln for ln in lines]
        return "\n".join(indent + ln if ln.strip() else ln for ln in trimmed)

    def _normalize_indent_bytes(self, block, indent):
        return block

    def _select_nodes(self):
        if not self.graph_nodes:
            return "run_graph_wall()", "run_graph_wall()"
        if len(self.graph_nodes) == 1:
            return f"{self.graph_nodes[0]}()", f"{self.graph_nodes[0]}()"
        n1, n2 = random.sample(self.graph_nodes, 2)
        return f"{n1}()", f"{n2}()"

    def visit(self, ast, content, file_path):
        funcs = self.find_nodes(ast, "FunctionDecl")
        content_bytes = content if isinstance(content, bytes) else content.encode("utf-8")

        for func in funcs:
            if not self._is_in_target_file(func, file_path):
                continue

            if self._has_vm_marker(content, func):
                continue

            inner = func.get("inner", [])
            body = None
            for child in inner:
                if child.get("kind") == "CompoundStmt":
                    body = child
                    break
            if not body:
                continue

            stmts = body.get("inner", []) or []
            if len(stmts) < self.min_frags:
                continue

            marked = self._has_marker(content, func)
            if not marked and not self._auto_candidate(func, len(stmts)):
                continue

            stmt_ranges = []
            for stmt in stmts:
                s, e = self.get_range(stmt)
                if s is None or e is None or s >= e:
                    stmt_ranges = []
                    break
                e = self._extend_stmt_end(s, e, content_bytes)
                stmt_ranges.append((s, e))
            if not stmt_ranges:
                continue

            stmt_texts = [content_bytes[s:e] for s, e in stmt_ranges]

            max_frags = min(self.max_frags, len(stmt_texts))
            frag_count = max_frags
            if max_frags > self.min_frags:
                frag_count = random.randint(self.min_frags, max_frags)

            cut_points = sorted(random.sample(range(1, len(stmt_texts)), frag_count - 1))
            fragments = []
            start = 0
            for cut in cut_points + [len(stmt_texts)]:
                frag = b"".join(stmt_texts[start:cut])
                fragments.append(frag)
                start = cut

            suffix = _rnd_suffix()
            path_var = f"_gs_path_{suffix}"
            label_prefix = f"_gs_frag_{suffix}_"
            branch_t_prefix = f"_gs_true_{suffix}_"
            branch_f_prefix = f"_gs_false_{suffix}_"

            path_bits = random.getrandbits(max(1, frag_count - 1))

            indent = "    ".encode("ascii")
            new_body = b"{\n"
            new_body += (f"{indent.decode()}volatile unsigned int {path_var} = 0x{path_bits:08X}u;\n").encode("ascii")

            for i, frag in enumerate(fragments):
                new_body += f"{indent.decode()}{label_prefix}{i}:\n".encode("ascii")
                new_body += self._normalize_indent(frag, indent * 2) + b"\n"

                if i < len(fragments) - 1:
                    bit_expr = f"(({path_var} >> {i}) & 1u)"
                    true_call, false_call = self._select_nodes()
                    new_body += f"{indent.decode()}if {bit_expr} goto {branch_t_prefix}{i}; else goto {branch_f_prefix}{i};\n".encode("ascii")
                    new_body += f"{indent.decode()}{branch_t_prefix}{i}:\n".encode("ascii")
                    new_body += f"{(indent * 2).decode()}{true_call};\n".encode("ascii")
                    new_body += f"{(indent * 2).decode()}goto {label_prefix}{i + 1};\n".encode("ascii")
                    new_body += f"{indent.decode()}{branch_f_prefix}{i}:\n".encode("ascii")
                    new_body += f"{(indent * 2).decode()}{false_call};\n".encode("ascii")
                    new_body += f"{(indent * 2).decode()}goto {label_prefix}{i + 1};\n".encode("ascii")

            new_body += b"}\n"

            body_start, body_end = self.get_range(body)
            if body_start is None or body_end is None:
                continue

            self.add_edit(body_start, body_end, new_body)
