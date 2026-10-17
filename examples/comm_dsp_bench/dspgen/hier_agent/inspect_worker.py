"""Execute an instrumented candidate in an isolated process and expose region contracts."""
from __future__ import annotations

import json
import sys
import traceback


def _signal(value, name, graph):
    try:
        from dspgraph.sdf import Sig
    except ModuleNotFoundError:
        from examples.comm_dsp_bench.dspgraph.sdf import Sig

    if not isinstance(value, Sig):
        return None
    period = None if value.lin is None else graph._lin[value.lin]["period"]
    return {
        "name": name,
        "width": value.w,
        "frac": value.f,
        "signed": value.signed,
        "rate_domain": value.lin,
        "clocks_per_sample": period,
        "latency": value.lat,
        "held": value.held,
    }


def _contracts(graph, names, env):
    contracts = []
    for name in names:
        value = env.get(name)
        if isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                contract = _signal(item, f"{name}[{index}]", graph)
                if contract:
                    contracts.append(contract)
        else:
            contract = _signal(value, name, graph)
            if contract:
                contracts.append(contract)
    return contracts


def _enter(graph, region_id, inputs, env):
    pending = getattr(graph, "_hier_pending", {})
    pending.setdefault(region_id, []).append(_contracts(graph, inputs, env))
    graph._hier_pending = pending


def _exit(graph, region_id, outputs, env):
    pending = getattr(graph, "_hier_pending", {})
    stack = pending.get(region_id, [])
    inputs = stack.pop() if stack else []
    row = {
        "region_id": region_id,
        "inputs": inputs,
        "outputs": _contracts(graph, outputs, env),
    }
    graph._hier_regions = getattr(graph, "_hier_regions", []) + [row]


def main():
    req = json.loads(sys.stdin.read())
    try:
        import math
        import numpy as np
        import scipy
        import scipy.signal

        from dspgraph.sdf import BuildError
        from dspgen.graph import TaskGraph
        from dspgen.task import get
        from dspgen.hier_agent.source import instrument_source

        task = get(req["task"])
        indexes = tuple(req.get("scenarios") or task.search_scenarios)
        x = np.stack([task.scene(i)["x_codes"] for i in indexes])
        xq = np.stack([task.scene(i)["xq_codes"] for i in indexes]) if task.iface("in_kind") == "complex" else None
        graph = TaskGraph(
            task.spec(),
            x,
            xq,
            in_kind=task.iface("in_kind"),
            out_kind=task.iface("out_kind"),
            in_period=task.iface("in_period"),
            out_period=task.iface("out_period"),
        )
        source, syntax = instrument_source(req["code"])
        env = {
            "np": np,
            "numpy": np,
            "scipy": scipy,
            "math": math,
            "__name__": "candidate",
            "__hier_enter": _enter,
            "__hier_exit": _exit,
        }
        exec(compile(source, "<candidate>", "exec"), env)
        if "build" not in env:
            raise BuildError("structure", "program must define build(g, spec)")
        env["build"](graph, task.spec())
        if graph.y is None:
            raise BuildError("structure", "build() never called g.output(...)")
        scores = [task.score(i, graph.y[k]) for k, i in enumerate(indexes)]
        result = {
            "ok": True,
            "quality": task.combine(scores),
            "area": graph.area(),
            "syntax": [vars(row) for row in syntax],
            "captures": getattr(graph, "_hier_regions", []),
        }
    except BuildError as exc:
        result = {"ok": False, "error": exc.as_dict()}
    except Exception as exc:
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((frame.lineno for frame in reversed(tb) if frame.filename == "<candidate>"), None)
        result = {
            "ok": False,
            "error": {"code": "python_error", "line": line, "message": f"{type(exc).__name__}: {str(exc)[:400]}"},
        }
    sys.stdout.write(json.dumps(result, default=float))


if __name__ == "__main__":
    main()
