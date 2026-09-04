// CommDSP-Bench: fir task — naive baseline
//
// 朴素实现：直接型 FIR，系数 Q1.15 定点，16 并行乘法器，单拍数据通路。
// 该文件是进化的初始程序，EVOLVE-BLOCK 标记内的代码可被改写。

module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] x,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [39:0] y
);

    // EVOLVE-BLOCK-START
    // 朴素基线：直接型 FIR（零初始历史），y = sum h_q[k]*x[n-k]，Q9.30 刻度
    reg signed [15:0] d0, d1, d2, d3, d4, d5, d6, d7;
    reg signed [15:0] d8, d9, d10, d11, d12, d13, d14, d15;

    wire signed [31:0] p0  = x    * -16'sd79;
    wire signed [31:0] p1  = d0  * -16'sd136;
    wire signed [31:0] p2  = d1  * 16'sd312;
    wire signed [31:0] p3  = d2  * 16'sd654;
    wire signed [31:0] p4  = d3  * -16'sd1244;
    wire signed [31:0] p5  = d4  * -16'sd2280;
    wire signed [31:0] p6  = d5  * 16'sd4501;
    wire signed [31:0] p7  = d6  * 16'sd14655;
    wire signed [31:0] p8  = d7  * 16'sd14655;
    wire signed [31:0] p9  = d8  * 16'sd4501;
    wire signed [31:0] p10 = d9  * -16'sd2280;
    wire signed [31:0] p11 = d10 * -16'sd1244;
    wire signed [31:0] p12 = d11 * 16'sd654;
    wire signed [31:0] p13 = d12 * 16'sd312;
    wire signed [31:0] p14 = d13 * -16'sd136;
    wire signed [31:0] p15 = d14 * -16'sd79;

    wire signed [39:0] acc  = p0 + p1 + p2 + p3 + p4 + p5 + p6 + p7;
    wire signed [39:0] acc2 = p8 + p9 + p10 + p11 + p12 + p13 + p14 + p15;
    wire signed [39:0] y_next = acc + acc2;

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            d0 <= 16'sd0; d1 <= 16'sd0; d2 <= 16'sd0; d3 <= 16'sd0;
            d4 <= 16'sd0; d5 <= 16'sd0; d6 <= 16'sd0; d7 <= 16'sd0;
            d8 <= 16'sd0; d9 <= 16'sd0; d10 <= 16'sd0; d11 <= 16'sd0;
            d12 <= 16'sd0; d13 <= 16'sd0; d14 <= 16'sd0; d15 <= 16'sd0;
            out_valid <= 1'b0;
            y <= 40'sd0;
        end else begin
            if (in_valid && in_ready) begin
            d15 <= d14;
            d14 <= d13;
            d13 <= d12;
            d12 <= d11;
            d11 <= d10;
            d10 <= d9;
            d9 <= d8;
            d8 <= d7;
            d7 <= d6;
            d6 <= d5;
            d5 <= d4;
            d4 <= d3;
            d3 <= d2;
            d2 <= d1;
            d1 <= d0;
                d0 <= x;
                y <= y_next;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
