// 3-real-multiplier exact complex multiply (Karatsuba) with 3-stage pipeline
//   real = ac - bd,  imag = (a+b)(c+d) - ac - bd = ad + bc
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] a,
    input  wire signed [15:0] b,
    input  wire signed [15:0] c,
    input  wire signed [15:0] d,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [32:0] y_re,
    output reg  signed [32:0] y_im
);
    // EVOLVE-BLOCK-START
    // Stage 1 registers
    reg signed [15:0] a1, b1, c1, d1;
    reg signed [16:0] ab1, cd1;
    reg v1;

    // Stage 2 registers
    reg signed [32:0] ac2, bd2;
    reg signed [34:0] abcd2;
    reg v2;

    assign in_ready = !(out_valid && !out_ready);

    always @(posedge clk) begin
        if (!rst_n) begin
            v1 <= 1'b0;
            v2 <= 1'b0;
            out_valid <= 1'b0;
            a1 <= 0; b1 <= 0; c1 <= 0; d1 <= 0;
            ab1 <= 0; cd1 <= 0;
            ac2 <= 0; bd2 <= 0; abcd2 <= 0;
            y_re <= 0; y_im <= 0;
        end else if (!(out_valid && !out_ready)) begin
            // Stage 1: register inputs and precompute sums
            a1 <= a;
            b1 <= b;
            c1 <= c;
            d1 <= d;
            ab1 <= a + b;
            cd1 <= c + d;
            v1 <= in_valid;

            // Stage 2: three multiplications
            ac2 <= a1 * c1;
            bd2 <= b1 * d1;
            abcd2 <= ab1 * cd1;
            v2 <= v1;

            // Stage 3: combine results and register output
            y_re <= ac2 - bd2;
            y_im <= abcd2 - ac2 - bd2;
            out_valid <= v2;
        end
    end
    // EVOLVE-BLOCK-END
endmodule