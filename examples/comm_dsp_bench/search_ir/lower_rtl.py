"""Deterministic search-IR lowering to synthesizable RTL."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chains.ddc import rtl_gen

from .canonicalize import candidate_hash
from .lower_bittrue import fir_node_config, leaf_nco_config, resolve_fir_coefficients
from .validate import validate_fir_node, validate_nco_node


def _rename_leaf_module(source: str, module_name: str) -> str:
    marker = "module nco_map ("
    if source.count(marker) != 1:
        raise RuntimeError("legacy NCO generator changed its module declaration")
    return source.replace(marker, f"module {module_name} (", 1)


def _compose_nco_map_rtl(node: Mapping[str, Any]) -> str:
    split_bits = int(node["split_bits"])
    shift = 32 - split_bits
    half = 1 << (shift - 1)
    child_nodes = [node["coarse"], node["residual"]]
    module_by_hash: dict[str, str] = {}
    definitions: list[str] = []
    for child in child_nodes:
        digest = candidate_hash(child)[:12]
        if digest not in module_by_hash:
            module_name = f"nco_leaf_{digest}"
            module_by_hash[digest] = module_name
            definitions.append(
                _rename_leaf_module(
                    rtl_gen.gen_nco_verilog(leaf_nco_config(child)), module_name
                )
            )
    coarse_module = module_by_hash[candidate_hash(node["coarse"])[:12]]
    residual_module = module_by_hash[candidate_hash(node["residual"])[:12]]
    rounding = node["product_rounding"]
    bias = 1 << 14 if rounding == "rne" else 0
    top = f"""// Generic phasor composition from search IR
module nco_map (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [31:0] phase_rounded = phase_acc + 32'h{half:08x};
    wire [31:0] coarse_acc = {{phase_rounded[31:{shift}], {{{shift}{{1'b0}}}}}};
    wire [31:0] residual_acc = phase_acc - coarse_acc;

    wire signed [15:0] coarse_sin, coarse_cos;
    wire signed [15:0] residual_sin, residual_cos;
    {coarse_module} u_coarse (
        .phase_acc(coarse_acc), .sin_o(coarse_sin), .cos_o(coarse_cos)
    );
    {residual_module} u_residual (
        .phase_acc(residual_acc), .sin_o(residual_sin), .cos_o(residual_cos)
    );

    wire signed [31:0] prod_cc = coarse_cos * residual_cos;
    wire signed [31:0] prod_ss = coarse_sin * residual_sin;
    wire signed [31:0] prod_sc = coarse_sin * residual_cos;
    wire signed [31:0] prod_cs = coarse_cos * residual_sin;
    wire signed [32:0] real_pre = {{prod_cc[31], prod_cc}} - {{prod_ss[31], prod_ss}};
    wire signed [32:0] imag_pre = {{prod_sc[31], prod_sc}} + {{prod_cs[31], prod_cs}};
    wire signed [32:0] real_q = (real_pre + 33'sd{bias}) >>> 15;
    wire signed [32:0] imag_q = (imag_pre + 33'sd{bias}) >>> 15;
    assign cos_o = (real_q > 32767) ? 16'sd32767 :
                   ((real_q < -32768) ? -16'sd32768 : real_q[15:0]);
    assign sin_o = (imag_q > 32767) ? 16'sd32767 :
                   ((imag_q < -32768) ? -16'sd32768 : imag_q[15:0]);
endmodule
"""
    return top + "\n" + "\n".join(definitions)


def lower_nco_map_rtl(node: Mapping[str, Any]) -> str:
    """Lower an NCO realization tree to a synthesizable ``nco_map`` module."""
    validate_nco_node(node)
    if node["kind"] == "phasor_compose":
        return _compose_nco_map_rtl(node)
    return rtl_gen.gen_nco_verilog(leaf_nco_config(node))


def _signed_decimal(width: int, value: int) -> str:
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


def _drop_product_lines(
    tag: str, source: str, coefficient: int, coefficient_width: int, config: Mapping[str, Any]
) -> tuple[list[str], str, int]:
    product_width = 17 + coefficient_width
    lines = [
        f"    wire signed [{product_width - 1}:0] prod_{tag} = "
        f"$signed({source}) * $signed({_signed_decimal(coefficient_width, coefficient)});"
    ]
    product_drop = int(config["prod_drop"])
    if product_drop:
        bias = 1 << (product_drop - 1) if config["mode"] == "rne" else 0
        lines.append(
            f"    wire signed [{product_width - 1}:0] prodq_{tag} = "
            f"((prod_{tag} + {_signed_decimal(product_width, bias)}) >>> "
            f"{product_drop}) <<< {product_drop};"
        )
        return lines, f"prodq_{tag}", product_width
    return lines, f"prod_{tag}", product_width


def _accumulate_lines(
    tag: str, terms: list[tuple[str, int]], accumulator_width: int
) -> tuple[list[str], str]:
    lines = []
    extended = []
    for index, (term, width) in enumerate(terms):
        extension = accumulator_width - width
        extended_name = f"term_{tag}_{index}"
        lines.append(
            f"    wire signed [{accumulator_width - 1}:0] {extended_name} = "
            f"{{{{{extension}{{{term}[{width - 1}]}}}}, {term}}};"
        )
        extended.append(extended_name)
    accumulator = f"acc_{tag}"
    lines.append(
        f"    wire signed [{accumulator_width - 1}:0] {accumulator} = "
        + " + ".join(extended)
        + ";"
    )
    return lines, accumulator


def _finish_accumulator_lines(
    tag: str, accumulator: str, accumulator_width: int, config: Mapping[str, Any]
) -> tuple[list[str], str]:
    lines = []
    declared_width = int(config["wacc"])
    saturated = f"accs_{tag}"
    if declared_width and declared_width < accumulator_width:
        high = (1 << (declared_width - 1)) - 1
        low = -(1 << (declared_width - 1))
        lines.append(
            f"    wire signed [{accumulator_width - 1}:0] {saturated} = "
            f"({accumulator} > {_signed_decimal(accumulator_width, high)}) ? "
            f"{_signed_decimal(accumulator_width, high)} : "
            f"(({accumulator} < {_signed_decimal(accumulator_width, low)}) ? "
            f"{_signed_decimal(accumulator_width, low)} : {accumulator});"
        )
    else:
        lines.append(
            f"    wire signed [{accumulator_width - 1}:0] {saturated} = {accumulator};"
        )
    shift = int(config["wc"]) - 2
    bias = 1 << (shift - 1) if config["mode"] == "rne" and shift else 0
    shifted = f"shifted_{tag}"
    lines.append(
        f"    wire signed [{accumulator_width - 1}:0] {shifted} = "
        f"({saturated} + {_signed_decimal(accumulator_width, bias)}) >>> {shift};"
    )
    output = f"out_{tag}"
    lines.append(
        f"    wire signed [15:0] {output} = ({shifted} > 32767) ? 16'sd32767 : "
        f"(({shifted} < -32768) ? -16'sd32768 : {shifted}[15:0]);"
    )
    return lines, output


def _direct_fir_body(hq: Any, config: Mapping[str, Any]) -> tuple[list[str], str, str]:
    taps = len(hq)
    coefficient_width = int(config["wc"])
    accumulator_width = 17 + coefficient_width + 6
    lines = [
        f"    reg signed [15:0] line_re [0:{taps - 2}];",
        f"    reg signed [15:0] line_im [0:{taps - 2}];",
    ]
    outputs = []
    for channel in ("re", "im"):
        input_name = f"x_{channel}"
        terms: list[tuple[str, int]] = []
        for tap in range(taps // 2):
            left = input_name if tap == 0 else f"line_{channel}[{tap - 1}]"
            right = f"line_{channel}[{taps - 2 - tap}]"
            pre = f"pre_{channel}_{tap}"
            lines.append(f"    wire signed [16:0] {pre} = $signed({left}) + $signed({right});")
            product_lines, product, width = _drop_product_lines(
                f"{channel}_{tap}", pre, int(hq[tap]), coefficient_width, config
            )
            lines.extend(product_lines)
            terms.append((product, width))
        center_source = f"{{line_{channel}[{taps // 2 - 1}][15], " \
            f"line_{channel}[{taps // 2 - 1}]}}"
        product_lines, product, width = _drop_product_lines(
            f"{channel}_center",
            center_source,
            int(hq[taps // 2]),
            coefficient_width,
            config,
        )
        lines.extend(product_lines)
        terms.append((product, width))
        accumulator_lines, accumulator = _accumulate_lines(
            f"direct_{channel}", terms, accumulator_width
        )
        lines.extend(accumulator_lines)
        finish_lines, output = _finish_accumulator_lines(
            f"direct_{channel}", accumulator, accumulator_width, config
        )
        lines.extend(finish_lines)
        outputs.append(output)
    lines.extend(
        [
            "    integer line_index;",
            "    always @(posedge clk) begin",
            "        if (!rst_n) begin",
            f"            for (line_index = 0; line_index < {taps - 1}; "
            "line_index = line_index + 1) begin",
            "                line_re[line_index] <= 16'sd0;",
            "                line_im[line_index] <= 16'sd0;",
            "            end",
            "        end else if (in_valid) begin",
            "            line_re[0] <= x_re;",
            "            line_im[0] <= x_im;",
            f"            for (line_index = 1; line_index < {taps - 1}; "
            "line_index = line_index + 1) begin",
            "                line_re[line_index] <= line_re[line_index - 1];",
            "                line_im[line_index] <= line_im[line_index - 1];",
            "            end",
            "        end",
            "    end",
        ]
    )
    return lines, outputs[0], outputs[1]


def _polyphase_branch_lines(
    channel: str,
    parity: int,
    hq: Any,
    config: Mapping[str, Any],
    accumulator_width: int,
) -> tuple[list[str], str]:
    coefficient_width = int(config["wc"])
    terms: list[tuple[str, int]] = []
    lines = []
    taps = list(range(parity, len(hq), 2))
    for branch_index, tap in enumerate(taps):
        source = (
            f"{{x_{channel}[15], x_{channel}}}"
            if branch_index == 0
            else f"{{phase_{channel}[{branch_index - 1}][15], "
            f"phase_{channel}[{branch_index - 1}]}}"
        )
        product_lines, product, width = _drop_product_lines(
            f"{channel}_p{parity}_{branch_index}",
            source,
            int(hq[tap]),
            coefficient_width,
            config,
        )
        lines.extend(product_lines)
        terms.append((product, width))
    accumulator_lines, accumulator = _accumulate_lines(
        f"{channel}_p{parity}", terms, accumulator_width
    )
    lines.extend(accumulator_lines)
    return lines, accumulator


def _polyphase_fir_body(hq: Any, config: Mapping[str, Any]) -> tuple[list[str], str, str]:
    coefficient_width = int(config["wc"])
    accumulator_width = 17 + coefficient_width + 6
    phase_depth = (len(hq) - 1) // 2
    lines = [
        f"    reg signed [15:0] even_re [0:{phase_depth - 1}];",
        f"    reg signed [15:0] even_im [0:{phase_depth - 1}];",
        f"    reg signed [15:0] odd_re [0:{phase_depth - 1}];",
        f"    reg signed [15:0] odd_im [0:{phase_depth - 1}];",
    ]
    totals = []
    odd_registers = []
    for channel in ("re", "im"):
        channel_lines = []
        branch_names = []
        for parity, prefix in ((0, "even"), (1, "odd")):
            branch_lines, accumulator = _polyphase_branch_lines(
                channel,
                parity,
                hq,
                config,
                accumulator_width,
            )
            branch_lines = [line.replace(f"phase_{channel}", f"{prefix}_{channel}")
                            for line in branch_lines]
            channel_lines.extend(branch_lines)
            branch_names.append(accumulator)
        lines.extend(channel_lines)
        odd_register = f"odd_partial_{channel}"
        odd_registers.append((odd_register, branch_names[1]))
        lines.append(f"    reg signed [{accumulator_width - 1}:0] {odd_register};")
        total = f"acc_poly_{channel}"
        lines.append(
            f"    wire signed [{accumulator_width - 1}:0] {total} = "
            f"{branch_names[0]} + {odd_register};"
        )
        finish_lines, output = _finish_accumulator_lines(
            f"poly_{channel}", total, accumulator_width, config
        )
        lines.extend(finish_lines)
        totals.append(output)
    lines.extend(
        [
            "    integer phase_index;",
            "    always @(posedge clk) begin",
            "        if (!rst_n) begin",
            f"            for (phase_index = 0; phase_index < {phase_depth}; "
            "phase_index = phase_index + 1) begin",
            "                even_re[phase_index] <= 16'sd0;",
            "                even_im[phase_index] <= 16'sd0;",
            "                odd_re[phase_index] <= 16'sd0;",
            "                odd_im[phase_index] <= 16'sd0;",
            "            end",
            f"            {odd_registers[0][0]} <= {accumulator_width}'sd0;",
            f"            {odd_registers[1][0]} <= {accumulator_width}'sd0;",
            "        end else if (in_valid) begin",
            "            if (sample_count[0] == 1'b0) begin",
            "                even_re[0] <= x_re;",
            "                even_im[0] <= x_im;",
            f"                for (phase_index = 1; phase_index < {phase_depth}; "
            "phase_index = phase_index + 1) begin",
            "                    even_re[phase_index] <= even_re[phase_index - 1];",
            "                    even_im[phase_index] <= even_im[phase_index - 1];",
            "                end",
            "            end else begin",
            "                odd_re[0] <= x_re;",
            "                odd_im[0] <= x_im;",
            f"                {odd_registers[0][0]} <= {odd_registers[0][1]};",
            f"                {odd_registers[1][0]} <= {odd_registers[1][1]};",
            f"                for (phase_index = 1; phase_index < {phase_depth}; "
            "phase_index = phase_index + 1) begin",
            "                    odd_re[phase_index] <= odd_re[phase_index - 1];",
            "                    odd_im[phase_index] <= odd_im[phase_index - 1];",
            "                end",
            "            end",
            "        end",
            "    end",
        ]
    )
    return lines, totals[0], totals[1]


def lower_fir_decimator_rtl(node: Mapping[str, Any]) -> str:
    """Lower a FIR / R=2 realization to a continuous-stream RTL module."""
    validate_fir_node(node)
    config = fir_node_config(node)
    hq = resolve_fir_coefficients(node)
    if node["kind"] == "direct_symmetric_fir_decimator":
        body, out_re, out_im = _direct_fir_body(hq, config)
    else:
        body, out_re, out_im = _polyphase_fir_body(hq, config)
    body_text = "\n".join(body)
    return f"""// FIR/decimator generated from search IR {candidate_hash(node)}
module fir_decimator (
    input  wire clk,
    input  wire rst_n,
    input  wire in_valid,
    input  wire signed [15:0] x_re,
    input  wire signed [15:0] x_im,
    output reg  signed [15:0] y_re,
    output reg  signed [15:0] y_im,
    output reg out_valid
);
    reg [31:0] sample_count;
{body_text}
    always @(posedge clk) begin
        if (!rst_n) begin
            sample_count <= 32'd0;
            y_re <= 16'sd0;
            y_im <= 16'sd0;
            out_valid <= 1'b0;
        end else begin
            out_valid <= 1'b0;
            if (in_valid) begin
                if ((sample_count >= 32) && (sample_count[0] == 1'b0)) begin
                    y_re <= {out_re};
                    y_im <= {out_im};
                    out_valid <= 1'b1;
                end
                sample_count <= sample_count + 32'd1;
            end
        end
    end
endmodule
"""
