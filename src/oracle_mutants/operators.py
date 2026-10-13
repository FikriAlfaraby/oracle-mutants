"""Mutation operators for reference-solution outputs.

Each operator takes the bytes of one output file and returns plausible-but-wrong
variants. A verifier that still awards full reward to one of these variants has a
gap worth a human look.

Severity says how sure we are that the variant is really wrong:
  strong  - almost never a valid answer (empty file, half the records gone, every number zeroed)
  medium  - usually wrong, but some verifiers rightly tolerate it (one record duplicated, a number off by +50%)
  weak    - formatting/order changes that a verifier may legitimately ignore (CRLF + BOM, two records swapped)
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from . import pyast

STRONG, MEDIUM, WEAK = "strong", "medium", "weak"

TEXT_EXT = {".txt", ".csv", ".tsv", ".md", ".sql", ".yaml", ".yml", ".rq", ".xml", ".musicxml", ".log", ".ini", ".toml", ".html", ".tex"}
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".c", ".h", ".cc", ".cpp", ".hpp", ".rs", ".go", ".java", ".kt",
            ".rb", ".php", ".sh", ".bash", ".sage", ".v", ".lean", ".sv", ".scala", ".swift", ".cs", ".lua", ".jl", ".r"}
JSON_EXT = {".json", ".jsonl", ".geojson"}

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
# A number that is a value on its own, not a piece of a date, time, path or ID ("2026-10-13", "run-00001").
FIELD_NUMBER = re.compile(r"(?<![\w.\-:/'\"])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.\-:/'\"])")


@dataclass(frozen=True)
class Variant:
    operator: str
    severity: str
    description: str
    data: bytes
    # For nudge-number only: the original number, and a function that writes the file with that
    # number moved by a given step. Used by the tolerance probe.
    value: str | None = field(default=None, compare=False)
    rebuild: Callable[[float], bytes] | None = field(default=None, compare=False, repr=False)


def shifted(token: str, step: float) -> str:
    """`token` moved up by `step`: integers by whole units (keeping zero padding), decimals relative to their size."""
    if re.fullmatch(r"-?\d+", token):
        bumped = str(int(token) + int(step))
        return bumped.zfill(len(token)) if token.startswith("0") and len(token) > 1 else bumped
    value = float(token)
    new = value * (1 + step) if value != 0 else step
    decimals = len(token.split(".")[1]) if "." in token and "e" not in token.lower() else 6
    return f"{new:.{decimals}f}"


def kind_of(path: str, data: bytes) -> str:
    ext = PurePosixPath(path).suffix.lower()
    try:
        data.decode("utf-8")
        is_text = b"\x00" not in data[:4096]
    except UnicodeDecodeError:
        is_text = False
    if not is_text:
        return "binary"
    if ext in JSON_EXT:
        return "json"
    if ext in CODE_EXT:
        return "code"
    return "text"


def mutate(path: str, data: bytes, max_per_operator: int = 3) -> list[Variant]:
    """All variants for one file, deduplicated and never equal to the original."""
    kind = kind_of(path, data)
    out: list[Variant] = []
    if data:
        out.append(Variant("empty", STRONG, "file emptied (0 bytes)", b""))
    if kind == "json":
        out += _json_variants(data)
    elif kind == "code":
        ext = PurePosixPath(path).suffix.lower()
        python = _python_variants(data.decode("utf-8"), max_per_operator) if ext in {".py", ".sage"} else []
        out += python or _code_variants(data.decode("utf-8"), max_per_operator, ext)
    elif kind == "text":
        out += _text_variants(path, data.decode("utf-8"))
    else:
        out += _binary_variants(data)
    seen: set[bytes] = {data}
    unique: list[Variant] = []
    for v in out:
        if v.data in seen:
            continue
        seen.add(v.data)
        unique.append(v)
    return unique


# --- text / tables -------------------------------------------------------

def _split(text: str) -> tuple[list[str], str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    return lines, newline


def _data_line_indexes(path: str, lines: list[str]) -> list[int]:
    idx = [i for i, line in enumerate(lines) if line.strip()]
    if PurePosixPath(path).suffix.lower() in {".csv", ".tsv"} and len(idx) > 1:
        idx = idx[1:]  # keep the header row
    return idx


def _text_variants(path: str, text: str) -> list[Variant]:
    lines, nl = _split(text)
    data_idx = _data_line_indexes(path, lines)
    out: list[Variant] = []

    def join(ls: list[str]) -> bytes:
        return nl.join(ls).encode("utf-8")

    if len(data_idx) >= 2:
        drop = set(data_idx[(len(data_idx) + 1) // 2:])
        out.append(Variant("truncate-half", STRONG, f"dropped the last {len(drop)} of {len(data_idx)} records",
                           join([line for i, line in enumerate(lines) if i not in drop])))
        last = data_idx[-1]
        out.append(Variant("drop-last-record", MEDIUM, f"dropped record on line {last + 1}",
                           join([line for i, line in enumerate(lines) if i != last])))
        a, b = data_idx[0], data_idx[1]
        if lines[a] != lines[b]:
            swapped = list(lines)
            swapped[a], swapped[b] = swapped[b], swapped[a]
            out.append(Variant("swap-records", WEAK, f"swapped lines {a + 1} and {b + 1}", join(swapped)))
    if data_idx:
        first = data_idx[0]
        out.append(Variant("duplicate-record", MEDIUM, f"duplicated record on line {first + 1}",
                           join(lines[: first + 1] + [lines[first]] + lines[first + 1:])))
    body_numbers = [m for i in data_idx for m in NUMBER.finditer(lines[i])]
    if body_numbers:
        zeroed = list(lines)
        for i in data_idx:
            zeroed[i] = NUMBER.sub("0", zeroed[i])
        out.append(Variant("numbers-to-zero", STRONG, f"set all {len(body_numbers)} numbers in records to 0", join(zeroed)))
        # Nudge a standalone value when there is one; the first number on a line is often a date or an ID.
        hits = [(i, FIELD_NUMBER.search(lines[i])) for i in data_idx]
        hits = [h for h in hits if h[1]] or [(i, NUMBER.search(lines[i])) for i in data_idx]
        for i, m in hits:
            if m:
                def rebuild(step: float, i=i, m=m) -> bytes:
                    nudged = list(lines)
                    nudged[i] = lines[i][: m.start()] + shifted(m.group(0), step) + lines[i][m.end():]
                    return join(nudged)

                out.append(Variant("nudge-number", MEDIUM, f"line {i + 1}: {m.group(0)} -> {_nudge(m.group(0))}",
                                   join([*lines[:i], lines[i][: m.start()] + _nudge(m.group(0)) + lines[i][m.end():], *lines[i + 1:]]),
                                   m.group(0), rebuild))
                break
    if nl == "\n":
        out.append(Variant("crlf-bom", WEAK, "re-encoded with a UTF-8 BOM and CRLF line endings",
                           ("﻿" + text.replace("\n", "\r\n")).encode("utf-8")))
    return out


def _nudge(token: str) -> str:
    """A clearly wrong but well-formed neighbour of a number: integers +1, decimals x1.5."""
    if re.fullmatch(r"-?\d+", token):
        bumped = str(int(token) + 1)
        return bumped.zfill(len(token)) if token.startswith("0") and len(token) > 1 else bumped
    value = float(token) * 1.5 if float(token) != 0 else 1.0
    decimals = len(token.split(".")[1]) if "." in token and "e" not in token.lower() else 6
    return f"{value:.{decimals}f}"


# --- JSON ----------------------------------------------------------------

def _json_variants(data: bytes) -> list[Variant]:
    text = data.decode("utf-8")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return _text_variants("x.txt", text)
    indent = 2 if "\n" in text.strip() else None

    def dump(obj) -> bytes:
        return (json.dumps(obj, indent=indent, ensure_ascii=False) + ("\n" if text.endswith("\n") else "")).encode("utf-8")

    out: list[Variant] = []
    if isinstance(doc, dict) and doc:
        out.append(Variant("empty-container", STRONG, "replaced the object with {}", dump({})))
        for key in list(doc)[:5]:
            out.append(Variant("drop-key", MEDIUM, f"removed top-level key {key!r}", dump({k: v for k, v in doc.items() if k != key})))
    if isinstance(doc, list) and doc:
        out.append(Variant("empty-container", STRONG, "replaced the array with []", dump([])))
        if len(doc) >= 2:
            out.append(Variant("truncate-half", STRONG, f"kept {len(doc) // 2} of {len(doc)} elements", dump(doc[: len(doc) // 2])))
            out.append(Variant("drop-last-record", MEDIUM, "removed the last element", dump(doc[:-1])))
        out.append(Variant("duplicate-record", MEDIUM, "duplicated the first element", dump([doc[0]] + doc)))
    # nested list of records (e.g. {"clusters": [...]}): truncate the first big list found
    path, lst = _first_list(doc)
    if path and len(lst) >= 2:
        out.append(Variant("truncate-half", STRONG, f"kept {len(lst) // 2} of {len(lst)} elements of {_fmt(path)}",
                           dump(_set(doc, path, lst[: len(lst) // 2]))))
        out.append(Variant("duplicate-record", MEDIUM, f"duplicated the first element of {_fmt(path)}",
                           dump(_set(doc, path, [lst[0]] + lst))))
    # Numbers under identifier keys ("id", "cluster_id", "userId") are labels, not values.
    leaves = [(p, v) for p, v in _numeric_leaves(doc) if not _is_id_path(p)]
    if leaves:
        keep = {p for p, _ in leaves}
        out.append(Variant("numbers-to-zero", STRONG, f"set all {len(leaves)} numeric values to 0",
                           dump(_map_numbers(doc, lambda v: 0, keep))))
        p, v = leaves[0]
        new = v + 1 if isinstance(v, int) else (v * 1.5 if v != 0 else 1.0)

        def rebuild_json(step: float, p=p, v=v) -> bytes:
            moved = v + int(step) if isinstance(v, int) else (v * (1 + step) if v != 0 else step)
            return dump(_set(doc, p, moved))

        out.append(Variant("nudge-number", MEDIUM, f"{_fmt(p)}: {v} -> {new}", dump(_set(doc, p, new)), json.dumps(v), rebuild_json))
        out.append(Variant("nullify", MEDIUM, f"{_fmt(p)}: {v} -> null", dump(_set(doc, p, None))))
    return out


def _fmt(path) -> str:
    return "".join(f"[{p!r}]" for p in path) or "<root>"


def _first_list(doc, path=()):
    if isinstance(doc, list) and path:
        return path, doc
    if isinstance(doc, dict):
        for k, v in doc.items():
            p, lst = _first_list(v, path + (k,))
            if p:
                return p, lst
    return None, None


def _numeric_leaves(doc, path=()):
    if isinstance(doc, bool):
        return
    if isinstance(doc, (int, float)):
        yield path, doc
    elif isinstance(doc, dict):
        for k, v in doc.items():
            yield from _numeric_leaves(v, path + (k,))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from _numeric_leaves(v, path + (i,))


def _map_numbers(doc, fn, keep=None, path=()):
    """Apply `fn` to numeric leaves; when `keep` is given, only to leaves whose path is in it."""
    if isinstance(doc, bool):
        return doc
    if isinstance(doc, (int, float)):
        return fn(doc) if keep is None or path in keep else doc
    if isinstance(doc, dict):
        return {k: _map_numbers(v, fn, keep, path + (k,)) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_map_numbers(v, fn, keep, path + (i,)) for i, v in enumerate(doc)]
    return doc


def _is_id_path(path) -> bool:
    last = next((p for p in reversed(path) if isinstance(p, str)), None)
    return last is not None and bool(re.search(r"(?:^|_)id$|[a-z]Id$|ID$", last))


def _set(doc, path, value):
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(doc, dict):
        copy = dict(doc)
        copy[head] = _set(doc[head], rest, value)
        return copy
    copy = list(doc)
    copy[head] = _set(doc[head], rest, value)
    return copy


# --- code ----------------------------------------------------------------

COMPARISONS = [(" == ", " != "), (" != ", " == "), (" <= ", " < "), (" >= ", " > "), (" < ", " <= "), (" > ", " >= ")]
BOOLS = [("True", "False"), ("False", "True"), ("true", "false"), ("false", "true")]
INT_LITERAL = re.compile(r"(?<![\w.])([2-9]|\d{2,})(?![\w.])")


def _is_comment(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith(("#", "//", "/*", "*", "--", "%"))


def _spread(items: list, k: int) -> list:
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


# Languages where a single quote opens an ordinary string; elsewhere it is a char literal or a lifetime.
SINGLE_QUOTE_STRINGS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rb", ".php", ".sh", ".bash", ".lua", ".r", ".jl", ".sage"}
HASH_COMMENTS = {".py", ".rb", ".sh", ".bash", ".r", ".jl", ".sage"}
CHAR_LITERAL = re.compile(r"'(?:\\.|[^\\'\n])'")


def _mask(src: str, ext: str) -> str:
    """`src` with every comment and string literal blanked to spaces (newlines kept), so operators only
    ever touch code. Positions line up with `src`."""
    if ext in {".py", ".sage"}:
        masked = _mask_python(src)
        if masked is not None:
            return masked
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for j in range(a, min(b, n)):
            if out[j] != "\n":
                out[j] = " "

    while i < n:
        c, two = src[i], src[i:i + 2]
        if two == "//" or (c == "#" and ext in HASH_COMMENTS):
            end = src.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif two == "/*":
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
        elif c in "\"`" or (c == "'" and ext in SINGLE_QUOTE_STRINGS):
            j = i + 1
            while j < n and src[j] != c and (c == "`" or src[j] != "\n"):
                j += 2 if src[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
        elif c == "'" and CHAR_LITERAL.match(src, i):
            end = CHAR_LITERAL.match(src, i).end()
            blank(i, end)
            i = end
        else:
            i += 1
    return "".join(out)


def _mask_python(src: str) -> str | None:
    lines = src.split("\n")
    out = [list(line) for line in lines]
    blanked = {tokenize.STRING, tokenize.COMMENT}
    if hasattr(tokenize, "FSTRING_MIDDLE"):
        blanked |= {tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in blanked:
                continue
            (r0, c0), (r1, c1) = tok.start, tok.end
            for r in range(r0 - 1, r1):
                a = c0 if r == r0 - 1 else 0
                b = c1 if r == r1 - 1 else len(out[r])
                for j in range(a, min(b, len(out[r]))):
                    out[r][j] = " "
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    return "\n".join("".join(line) for line in out)


def _code_variants(src: str, k: int, ext: str = "") -> list[Variant]:
    lines = src.split("\n")
    code = _mask(src, ext).split("\n")  # same shape as `lines`, comments and strings blanked
    out: list[Variant] = []
    sites = []
    for i, line in enumerate(code):
        if _is_comment(line):
            continue
        for a, b in COMPARISONS:
            j = line.find(a)
            if j >= 0:
                sites.append((i, j, a, b))
                break
    for i, j, a, b in _spread(sites, k):
        m = list(lines)
        m[i] = lines[i][:j] + b + lines[i][j + len(a):]
        out.append(Variant("flip-comparison", MEDIUM, f"line {i + 1}: '{a.strip()}' -> '{b.strip()}'", "\n".join(m).encode("utf-8")))
    sites = [(i, mt) for i, line in enumerate(code) if not _is_comment(line) for mt in [INT_LITERAL.search(line)] if mt]
    for i, mt in _spread(sites, k):
        m = list(lines)
        m[i] = lines[i][: mt.start()] + str(int(mt.group(0)) + 1) + lines[i][mt.end():]
        out.append(Variant("off-by-one-constant", MEDIUM, f"line {i + 1}: {mt.group(0)} -> {int(mt.group(0)) + 1}", "\n".join(m).encode("utf-8")))
    sites = []
    for i, line in enumerate(code):
        if _is_comment(line):
            continue
        for a, b in BOOLS:
            mt = re.search(rf"(?<![\w]){a}(?![\w])", line)
            if mt:
                sites.append((i, mt, b))
                break
    for i, mt, b in _spread(sites, max(1, k - 1)):
        m = list(lines)
        m[i] = lines[i][: mt.start()] + b + lines[i][mt.end():]
        out.append(Variant("flip-boolean", MEDIUM, f"line {i + 1}: {mt.group(0)} -> {b}", "\n".join(m).encode("utf-8")))
    return out


def _python_variants(src: str, k: int) -> list[Variant]:
    """Python goes through the syntax tree (see pyast). `k` caps the sites per operator, spread over the
    file; pass a large `k` for exhaustive mutation."""
    by_op: dict[str, list] = {}
    for site in pyast.sites(src):
        by_op.setdefault(site.operator, []).append(site)
    out = []
    for op_sites in by_op.values():
        for site in _spread(op_sites, k):
            out.append(Variant(site.operator, MEDIUM, site.description, pyast.apply(src, site).encode("utf-8")))
    return out


# --- binary --------------------------------------------------------------

def _binary_variants(data: bytes) -> list[Variant]:
    out: list[Variant] = []
    if len(data) >= 2:
        out.append(Variant("truncate-half", STRONG, f"kept the first {len(data) // 2} of {len(data)} bytes", data[: len(data) // 2]))
    if len(data) >= 64:
        mid = len(data) // 2
        flipped = data[:mid] + bytes(b ^ 0xFF for b in data[mid: mid + 16]) + data[mid + 16:]
        out.append(Variant("corrupt-bytes", STRONG, f"inverted 16 bytes at offset {mid}", flipped))
    return out
