"""certfit llr_64qam_snr20 — L2 max-log datapath, precision-leaning point.

Knobs / rationale:
  metric       "l2"  the only certificate norm that yields a valid score
                     (l1 variants produced invalid / zero certificates).
  corr_entries 0     the correction-table RTL path is params_invalid, so the
                     pure max-log datapath is the only legal configuration.
  corr_frac    6     fixed-point fraction width.  The {6, 8} points evaluate
                     identically (same precision AND same area), so we take the
                     minimum value — it costs nothing.
  input_trunc  5     one bit LESS input pre-truncation than the previous corner.
                     This is the only knob that actually moves the certificate,
                     since quantization noise scales as 2^(2*input_trunc):
                     dropping 6 -> 5 cuts truncation-noise power by ~4x (~+6 dB
                     SQNR) for only a modest datapath-width increase.  The
                     previous program pinned input_trunc at the max (6) purely
                     for area/time safety; input_trunc=4 already exceeded the
                     300 s stage-2 budget, so 5 is the next precision tier that
                     remains adjacent to the proven-safe input_trunc=6 design.
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "metric": "l2",
    "corr_entries": 0,
    "corr_frac": 6,
    "input_trunc": 5,
}
# EVOLVE-BLOCK-END