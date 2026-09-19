// CommDSP-Bench: cmul anchor task — naive baseline
//
// 朴素实现：4 个并行乘法器 + 加减法，单拍组合数据通路。
// 该文件是进化的初始程序，EVOLVE-BLOCK 标记内的代码可被改写。

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
    // 高斯三乘法器复数乘法 (3-multiplier complex multiply, area-optimized)
    //   p1=(a+b)c, p2=a(d-c), p3=b(c+d)
    //   y_re = p1-p3 = ac-bd , y_im = p1+p2 = ad+bc  (exact in integers)
    assign in_ready = 1'b1;

    wire signed [16:0] sum_ab = a + b;
    wire signed [16:0] dif_dc = d - c;
    wire signed [16:0] sum_cd = c + d;

    wire signed [32:0] p1 = sum_ab * c;
    wire signed [32:0] p2 = a      * dif_dc;
    wire signed [32:0] p3 = b      * sum_cd;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            y_re      <= 33'sd0;
            y_im      <= 33'sd0;
        end else begin
            if (in_valid && in_ready) begin
                y_re <= p1 - p3;
                y_im <= p1 + p2;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
