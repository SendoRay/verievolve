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
    // 3-multiplier complex multiply (Gauss / Karatsuba trick):
    //   t1 = a*c, t2 = b*d, t3 = (a+b)*(c+d)
    //   y_re = t1 - t2
    //   y_im = t3 - t1 - t2          (= ad + bc, exact)
    // Exact integer arithmetic -> 4 multipliers reduced to 3, area down,
    // precision (SQNR) preserved because nothing is rounded/truncated.
    assign in_ready = 1'b1;

    // 17-bit signed sums (range fits exactly in signed 17 bit)
    wire signed [16:0] a_pb = {a[15], a} + {b[15], b};
    wire signed [16:0] c_pd = {c[15], c} + {d[15], d};

    wire signed [31:0] t1 = a * c;      // 16x16
    wire signed [31:0] t2 = b * d;      // 16x16
    wire signed [32:0] t3 = a_pb * c_pd; // 17x17 -> fits exactly in 33 bit

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            y_re      <= 33'sd0;
            y_im      <= 33'sd0;
        end else begin
            if (in_valid && in_ready) begin
                y_re <= t1 - t2;
                y_im <= t3 - t1 - t2;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
