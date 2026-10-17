"""Structured source analysis and parameter edits for primitive build programs."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegionSyntax:
    region_id: str
    name: str
    line: int
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


def _scope_name(node: ast.With) -> str | None:
    if len(node.items) != 1:
        return None
    call = node.items[0].context_expr
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr != "scope" or len(call.args) != 1:
        return None
    arg = call.args[0]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


class _Names(ast.NodeVisitor):
    def __init__(self):
        self.loads: set[str] = set()
        self.stores: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.stores.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stores.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _names(nodes: list[ast.stmt]) -> _Names:
    out = _Names()
    for node in nodes:
        out.visit(node)
    return out


def _live_in(nodes: list[ast.stmt]) -> set[str]:
    """Names whose current values are read before the suffix redefines them."""
    return _transfer_block(nodes, set())


def _transfer_block(nodes: list[ast.stmt], live_after: set[str]) -> set[str]:
    live = set(live_after)
    for node in reversed(nodes):
        live = _transfer(node, live)
    return live


def _transfer(node: ast.stmt, live_after: set[str]) -> set[str]:
    if isinstance(node, ast.With):
        live = _transfer_block(node.body, live_after)
        context = _names([ast.Expr(item.context_expr) for item in node.items])
        return (live - context.stores) | context.loads
    if isinstance(node, ast.If):
        body = _transfer_block(node.body, live_after)
        other = _transfer_block(node.orelse, live_after)
        test = _names([ast.Expr(node.test)])
        return body | other | test.loads
    names = _names([node])
    return (live_after - names.stores) | names.loads


def find_regions(source: str) -> list[RegionSyntax]:
    """Find literal ``with g.scope(name)`` regions and their live boundary names."""
    tree = ast.parse(source)
    regions: list[RegionSyntax] = []
    counts: dict[str, int] = {}

    def scan(body: list[ast.stmt]) -> None:
        for index, stmt in enumerate(body):
            if isinstance(stmt, ast.With):
                name = _scope_name(stmt)
                if name is not None:
                    inside = _names(stmt.body)
                    inputs = _live_in(stmt.body)
                    live_after = _live_in(body[index + 1 :])
                    ordinal = counts.get(name, 0)
                    counts[name] = ordinal + 1
                    region_id = f"{name}@{stmt.lineno}#{ordinal}"
                    regions.append(
                        RegionSyntax(
                            region_id=region_id,
                            name=name,
                            line=stmt.lineno,
                            inputs=tuple(sorted(inputs)),
                            outputs=tuple(sorted(inside.stores & live_after)),
                        )
                    )
                scan(stmt.body)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scan(stmt.body)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.Try)):
                for child in ("body", "orelse", "finalbody"):
                    scan(getattr(stmt, child, []))
                for handler in getattr(stmt, "handlers", []):
                    scan(handler.body)

    scan(tree.body)
    return regions


class _Instrument(ast.NodeTransformer):
    def __init__(self, regions: list[RegionSyntax]):
        self.by_line = {r.line: r for r in regions}

    def visit_With(self, node: ast.With):
        node = self.generic_visit(node)
        region = self.by_line.get(node.lineno)
        if region is None or _scope_name(node) is None:
            return node
        enter = ast.Expr(
            ast.Call(
                func=ast.Name(id="__hier_enter", ctx=ast.Load()),
                args=[
                    ast.Name(id="g", ctx=ast.Load()),
                    ast.Constant(region.region_id),
                    ast.List([ast.Constant(v) for v in region.inputs], ast.Load()),
                    ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[]),
                ],
                keywords=[],
            )
        )
        exit_ = ast.Expr(
            ast.Call(
                func=ast.Name(id="__hier_exit", ctx=ast.Load()),
                args=[
                    ast.Name(id="g", ctx=ast.Load()),
                    ast.Constant(region.region_id),
                    ast.List([ast.Constant(v) for v in region.outputs], ast.Load()),
                    ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[]),
                ],
                keywords=[],
            )
        )
        return [ast.copy_location(enter, node), node, ast.copy_location(exit_, node)]


def instrument_source(source: str) -> tuple[str, list[RegionSyntax]]:
    regions = find_regions(source)
    tree = _Instrument(regions).visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", regions


class _TuneParameter(ast.NodeTransformer):
    def __init__(self, edits: dict[str, Any], mapping_name: str):
        self.edits = edits
        self.mapping_name = mapping_name
        self.applied: set[str] = set()

    def visit_Assign(self, node: ast.Assign):
        node = self.generic_visit(node)
        if not any(isinstance(t, ast.Name) and t.id == self.mapping_name for t in node.targets):
            return node
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "dict":
            for keyword in node.value.keywords:
                if keyword.arg in self.edits:
                    keyword.value = _literal(self.edits[keyword.arg])
                    self.applied.add(keyword.arg)
        elif isinstance(node.value, ast.Dict):
            for index, key in enumerate(node.value.keys):
                if isinstance(key, ast.Constant) and key.value in self.edits:
                    node.value.values[index] = _literal(self.edits[key.value])
                    self.applied.add(key.value)
        return node


def _literal(value: Any) -> ast.expr:
    return ast.parse(repr(value), mode="eval").body


def tune_parameters(source: str, edits: dict[str, Any], mapping_name: str = "P") -> str:
    """Apply literal edits to a top-level parameter mapping using Python's AST."""
    tree = ast.parse(source)
    transform = _TuneParameter(edits, mapping_name)
    tree = transform.visit(tree)
    missing = set(edits) - transform.applied
    if missing:
        raise ValueError(f"parameters not found in {mapping_name}: {sorted(missing)}")
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"
