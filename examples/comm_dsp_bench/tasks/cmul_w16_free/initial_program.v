// 参数化基线：复数乘法 4 乘法器（16 位，free）
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
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; y_re <= 0; y_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                y_re <= a * c - b * d; y_im <= a * d + b * c;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
