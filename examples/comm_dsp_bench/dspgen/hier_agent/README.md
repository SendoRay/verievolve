# LLM-driven hierarchical search prototype

This directory contains a development prototype for searching primitive programs
toward an adaptive-granularity AND/OR tree. It is not yet a paper result.

## Search state

- An OR node is a typed region problem under a boundary contract; alternative
  rewrites or tunings are choices for that same problem.
- An AND node is one selected decomposition whose child regions must all be
  instantiated and assembled before the branch is a complete candidate.
- The current prototype materializes every proposed combination as a complete
  primitive program and evaluates it at the chain root. It preserves OR branches
  and region boundaries, but does not yet solve and compose independent child
  frontiers; therefore current runs are not evidence for strict AND/OR backup.
- `EXPAND`, `DECOMPOSE`, and `FUSE` candidates are proposed as complete programs
  by an LLM agent. `TUNE` applies structured edits to the program's `P` mapping.
- Every candidate is checked at the chain root. A locally cheaper candidate below
  the configured root margin cannot dominate a feasible candidate.
- Feasible candidates are retained as a conditional Pareto frontier over proxy
  area, root margin, and ripple. The root program is append-only and is never
  overwritten by a child.

Literal `g.scope(...)` blocks provide initial node boundaries. Static liveness
finds boundary names, while entry/exit probes recover the dynamic signal contract:
width, fractional bits, signedness, rate domain, clocks per sample, latency, and
held semantics. The tree can still cross these initial boundaries through `FUSE`
or replace them through `DECOMPOSE`.

Scope widening is recorded only as an intervention response. It is not treated as
an additive or monotonic error attribution; widening an outer scope can change LUT
formats and make the root metric worse.

## Development replay

From `examples/comm_dsp_bench`:

```bash
python3 -m dspgen.hier_agent.cli \
  --task dev_r32_narrow \
  --out experiments_hier_agent/r32n_codex_v3 \
  init --seed /path/to/program.py

python3 -m dspgen.hier_agent.cli \
  --task dev_r32_narrow \
  --out experiments_hier_agent/r32n_codex_v3 \
  tune --parent CANDIDATE_ID --set mix_w=14 \
  --rationale "LLM decision recorded in the search tree"
```

The exact development run is stored in
`experiments_hier_agent/r32n_codex_v3/state.json`. It is a single adaptive run
using the search scenarios and proxy area. Any selected new design still requires
independent holdout, RTL bit-true comparison, and real synthesis before it can be
reported as a hardware result.
