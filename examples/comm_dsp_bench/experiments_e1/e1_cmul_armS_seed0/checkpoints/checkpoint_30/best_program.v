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
    // 3-mult complex multiply (Karatsuba/Gauss):
    //   p1=a*c, p2=b*d, p3=(a+b)*(c+d)
    //   y_re = p1 - p2 ;  y_im = p3 - (p1 + p2)   (== a*d + b*c)
    // Lossless full-throughput handshake: in_ready is deasserted only when a
    // pending output would otherwise be overwritten (backpressure), so no
    // result is ever dropped while still sustaining 1 sample/cycle when
    // out_ready is asserted.
    assign in_ready = ~out_valid | out_ready;

    wire signed [16:0] ab = a + b;   // s = a+b (17-bit)
    wire signed [16:0] cd = c + d;   // t = c+d (17-bit)

    wire signed [31:0] p1 = a * c;   // a*c
    wire signed [31:0] p2 = b * d;   // b*d

    // Only the low 33 bits of s*t are needed.  Writing
    //   s = su - Sb*2^16,  t = tu - Tb*2^16   (su,tu 16-bit unsigned)
    // gives  s*t = su*tu - 2^16*(Sb*tu + Tb*su) + 2^32*(Sb&Tb),
    // so the 17x17 product is replaced by a 16x16 unsigned multiply plus
    // small corrections -- shrinking the third multiplier.
    wire [15:0] su = ab[15:0];
    wire [15:0] tu = cd[15:0];
    wire        Sb = ab[16];
    wire        Tb = cd[16];
    wire [31:0] pu   = su * tu;
    wire [16:0] corr = (Sb ? {1'b0, tu} : 17'd0) + (Tb ? {1'b0, su} : 17'd0);
    wire [33:0] p3   = {2'b0, pu} - {1'b0, corr, 16'b0}
                       + (Sb & Tb ? 34'h1_0000_0000 : 34'd0);

    wire signed [32:0] p1e = {p1[31], p1};
    wire signed [32:0] p2e = {p2[31], p2};
    wire signed [32:0] p3l = p3[32:0];
    wire signed [32:0] re_n = p1e - p2e;              // a*c - b*d
    wire signed [32:0] im_n = p3l - p1e - p2e;        // (a+b)(c+d) - a*c - b*d

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            y_re      <= 33'sd0;
            y_im      <= 33'sd0;
        end else if (in_valid && in_ready) begin
            y_re      <= re_n;        // a*c - b*d
            y_im      <= im_n;        // (a+b)(c+d) - a*c - b*d
            out_valid <= 1'b1;
        end else if (out_valid && out_ready) begin
            out_valid <= 1'b0;
        end
    end
    // EVOLVE-BLOCK-END

endmodule
