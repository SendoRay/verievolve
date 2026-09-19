// certfit 参数化复数乘法器 so=0 sd=0 mode=rne structure=karatsuba
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


    wire signed [33:0] pac = $signed(a) * $signed(c);
    wire signed [33:0] pbd = $signed(b) * $signed(d);
    wire signed [17:0] sab = $signed(a) + $signed(b);
    wire signed [17:0] scd = $signed(c) + $signed(d);
    wire signed [35:0] p1 = sab * scd;

    wire signed [34:0] pac_x = pac;
    wire signed [34:0] pbd_x = pbd;
    wire signed [34:0] p1_x = p1;
    wire signed [34:0] re_pre = (pac_x - pbd_x) <<< 0;
    wire signed [34:0] im_pre = (p1_x - pac_x - pbd_x) <<< 0;

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; y_re <= 0; y_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                y_re <= re_pre[32:0]; y_im <= im_pre[32:0];
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
