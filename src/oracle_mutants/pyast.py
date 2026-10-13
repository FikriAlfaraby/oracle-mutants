"""Exhaustive Python mutants from the syntax tree, using the standard operator families of mutation
testing tools (PIT, Stryker, mutmut): relational replacement, condition replacement, arithmetic
replacement, constant replacement, boolean flip, and method swaps.

Working on the tree means a site is always real code: never a comment, a string or a docstring, and
the edit covers exactly the expression it names.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# Relational operator replacement: the boundary shift and the negation of each operator.
ROR = {
    ast.Lt: ("<", ["<=", ">="]), ast.LtE: ("<=", ["<", ">"]),
    ast.Gt: (">", [">=", "<="]), ast.GtE: (">=", [">", "<"]),
    ast.Eq: ("==", ["!="]), ast.NotEq: ("!=", ["=="]),
}
AOR = {ast.Add: ("+", "-"), ast.Sub: ("-", "+"), ast.Mult: ("*", "/"), ast.Div: ("/", "*"),
       ast.FloorDiv: ("//", "/"), ast.Mod: ("%", "/")}
BOUNDARY = {("<", "<="), ("<=", "<"), (">", ">="), (">=", ">")}
SWAPS = {"min": "max", "max": "min", "any": "all", "all": "any"}


@dataclass(frozen=True)
class Site:
    operator: str
    line: int          # 1-based
    description: str
    start: int         # absolute character offsets into the source
    end: int
    replacement: str


def sites(src: str) -> list[Site]:
    """Every mutation site in a Python source, in source order. Empty when the source does not parse."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    offsets = _line_offsets(src)
    lines = src.splitlines(keepends=True) + [""]

    def at(lineno: int, col: int) -> int:
        # The tree reports columns in UTF-8 bytes; turn them into character offsets.
        return offsets[lineno - 1] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "ignore"))

    def pos(node) -> tuple[int, int]:
        return at(node.lineno, node.col_offset), at(node.end_lineno, node.end_col_offset)

    # Formatting knobs, not values: round(x, 1) -> round(x, 2) or json.dump(..., indent=2) -> 3 only
    # change how a result is printed.
    formatting = {id(n.args[1]) for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round" and len(n.args) > 1}
    formatting |= {id(k.value) for n in ast.walk(tree) if isinstance(n, ast.Call)
                   for k in n.keywords if k.arg in {"ndigits", "indent"}}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    out: list[Site] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in ROR:
            a, b = pos(node)
            text = src[a:b]
            left_end = at(node.left.end_lineno, node.left.end_col_offset)
            right_start = at(node.comparators[0].lineno, node.comparators[0].col_offset)
            sym, alts = ROR[type(node.ops[0])]
            gap = src[left_end:right_start]
            for alt in alts:
                kind = "flip-comparison" if (sym, alt) in BOUNDARY else "negate-comparison"
                out.append(Site(kind, node.lineno, f"line {node.lineno}: '{sym}' -> '{alt}'",
                                left_end, right_start, gap.replace(sym, alt, 1)))
            if _is_condition(node, tree):
                for const in ("True", "False"):
                    out.append(Site("condition-to-constant", node.lineno,
                                    f"line {node.lineno}: '{_short(text)}' -> {const}", a, b, const))
        elif isinstance(node, ast.BinOp) and type(node.op) in AOR and not _is_text(node.left):
            sym, alt = AOR[type(node.op)]
            left_end = at(node.left.end_lineno, node.left.end_col_offset)
            right_start = at(node.right.lineno, node.right.col_offset)
            gap = src[left_end:right_start]
            if sym in gap:
                out.append(Site("swap-arithmetic", node.lineno, f"line {node.lineno}: '{sym}' -> '{alt}'",
                                left_end, right_start, gap.replace(sym, alt, 1)))
        elif isinstance(node, ast.Constant) and id(node) not in docstrings and id(node) not in formatting:
            a, b = pos(node)
            if isinstance(node.value, bool):
                flipped = str(not node.value)
                out.append(Site("flip-boolean", node.lineno, f"line {node.lineno}: {node.value} -> {flipped}", a, b, flipped))
            elif isinstance(node.value, (int, float)) and src[a:b].lstrip("-").replace(".", "", 1).replace("_", "").isdigit():
                new = repr(node.value + 1)
                out.append(Site("off-by-one-constant", node.lineno, f"line {node.lineno}: {src[a:b]} -> {new}", a, b, new))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SWAPS:
            a, b = pos(node.func)
            alt = SWAPS[node.func.id]
            out.append(Site("swap-call", node.lineno, f"line {node.lineno}: {node.func.id}() -> {alt}()", a, b, alt))
    out.sort(key=lambda s: (s.start, s.operator, s.replacement))
    return out


def apply(src: str, site: Site) -> str:
    return src[: site.start] + site.replacement + src[site.end:]


def _is_text(node: ast.AST) -> bool:
    """`"..." % x` and f-strings are formatting, not arithmetic."""
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)))


def _is_condition(node: ast.AST, tree: ast.AST) -> bool:
    """A comparison that decides control flow or is returned/assigned as a flag."""
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.If, ast.While, ast.IfExp, ast.Assert)) and parent.test is node:
            return True
        if isinstance(parent, (ast.Return, ast.Assign, ast.AnnAssign)) and getattr(parent, "value", None) is node:
            return True
        if isinstance(parent, ast.BoolOp) and node in parent.values:
            return True
    return False


def _short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _line_offsets(src: str) -> list[int]:
    offsets, total = [], 0
    for line in src.splitlines(keepends=True):
        offsets.append(total)
        total += len(line)
    offsets.append(total)
    return offsets
