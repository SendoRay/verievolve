"""certfit: sine/cosine generator parameter block.

Search knobs (precision / area / throughput Pareto is kept by MAP-Elites):
  algo   : "lut" | "cordic"
  order  : "nearest" | "linear" | "quad"   (lut only)
  depth  : 64/128/256/512/1024             (lut full-wave ROM depth)
  stages : 8..20                           (cordic iterations)

Strategy:
  The certificate SQNR saturates at the ~61.4 dB output-word cap.
  Quadratic interpolation (area ≈ 4966) buys only +0.33 dB over linear
  (area ≈ 2220) — a net loss because area is the dominant penalty.
  Linear interpolation at the minimum ROM depth 64 already sits at
  ~61.1 dB, i.e. ~99.5% of the cap, while keeping LUT area minimal,
  maximising the precision/area trade-off.
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "algo": "lut",
    "order": "linear",
    "depth": 64,
    "stages": 12,
}
# EVOLVE-BLOCK-END