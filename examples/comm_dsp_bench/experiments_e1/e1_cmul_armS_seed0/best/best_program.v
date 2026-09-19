// CommDSP-Bench: cmul anchor task — Karatsuba (3-mult) complex multiplier
//
// 用 3 个乘法器实现复数乘法（Karatsuba 技巧），减少 LUT 面积：
//   y_re = a*c - b*d
//   y_im = (a+b)*(c+d) - a*c - b*d

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
    // 3 个乘法器（Karatsuba / Gauss）：
    //   p1 = a*c , p2 = b*d , p3 = (a+b)*(c+d)
    //   y_re = p1 - p2 , y_im = p3 - p1 - p2
    //
    // 符号扩展到 17 bit（a+b 范围 -65536..65534）；上下文宽度会自动扩展，
    // 无需显式拼接。
    wire signed [16:0] ab = a + b;   // a+b
    wire signed [16:0] cd = c + d;   // c+d

    wire signed [31:0] p1 = a * c;   // a*c
    wire signed [31:0] p2 = b * d;   // b*d

    // 只需 (a+b)*(c+d) 的低 33 位。利用
    //   s = su - Sb*2^16 , t = tu - Tb*2^16   (su,tu 为低 16 位无符号数)
    // 得到  s*t = su*tu - 2^16*(Sb*tu + Tb*su) + 2^32*(Sb&Tb)，
    // 于是 17x17 乘法被替换为一个 16x16 无符号乘法加少量修正项，
    // 在保持逐位精确的同时显著减少 LUT。整个数据通路按 mod 2^33 运算，
    // 结果恰好落在 33bit 有符号范围内。
    wire [15:0] su = ab[15:0];
    wire [15:0] tu = cd[15:0];
    wire        Sb = ab[16];
    wire        Tb = cd[16];
    wire [31:0] pu   = su * tu;
    wire [16:0] corr = (Sb ? {1'b0, tu} : 17'd0) + (Tb ? {1'b0, su} : 17'd0);
    wire signed [32:0] p3 = {1'b0, pu} - {corr, 16'b0}
                            + (Sb & Tb ? 33'h1_0000_0000 : 33'd0);

    wire signed [32:0] p1e = {p1[31], p1};
    wire signed [32:0] p2e = {p2[31], p2};
    wire signed [32:0] re_n = p1e - p2e;        // a*c - b*d
    wire signed [32:0] im_n = p3  - p1e - p2e;  // (a+b)(c+d) - a*c - b*d

    assign in_ready = 1'b1;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            y_re      <= 33'sd0;
            y_im      <= 33'sd0;
        end else begin
            if (in_valid && in_ready) begin
                y_re      <= re_n;
                y_im      <= im_n[32:0];
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule