// 参数化基线：64QAM max-log LLR（v4：abs 距离 + (d1-d0)(d1+d0)，朴素）
// 2σ²归一 Q8.8 与 golden 同口径；距离差 = m1 - m0（bit=0 证据强 → 正 LLR）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg signed [15:0] llr0, output reg signed [15:0] llr1, output reg signed [15:0] llr2, output reg signed [15:0] llr3, output reg signed [15:0] llr4, output reg signed [15:0] llr5
);
    // EVOLVE-BLOCK-START
    function [17:0] minu18;
        input [17:0] a;
        input [17:0] b;
        begin
            minu18 = (a < b) ? a : b;
        end
    endfunction
    // 拼接是无符号上下文：符号扩展必须显式补满位（16→20）
    wire signed [19:0] yi = {{4{i_in[15]}}, i_in};
    wire signed [19:0] yq = {{4{q_in[15]}}, q_in};
    wire signed [19:0] A0 = 20'sd4096;
    wire signed [19:0] A1 = 20'sd12288;
    wire signed [19:0] A2 = 20'sd28672;
    wire signed [19:0] A3 = 20'sd20480;
    wire signed [19:0] A4 = -20'sd20480;
    wire signed [19:0] A5 = -20'sd28672;
    wire signed [19:0] A6 = -20'sd12288;
    wire signed [19:0] A7 = -20'sd4096;
    wire signed [19:0] dyi0 = yi - A0;  wire signed [19:0] ndyi0 = -dyi0;
    wire signed [19:0] dyi1 = yi - A1;  wire signed [19:0] ndyi1 = -dyi1;
    wire signed [19:0] dyi2 = yi - A2;  wire signed [19:0] ndyi2 = -dyi2;
    wire signed [19:0] dyi3 = yi - A3;  wire signed [19:0] ndyi3 = -dyi3;
    wire signed [19:0] dyi4 = yi - A4;  wire signed [19:0] ndyi4 = -dyi4;
    wire signed [19:0] dyi5 = yi - A5;  wire signed [19:0] ndyi5 = -dyi5;
    wire signed [19:0] dyi6 = yi - A6;  wire signed [19:0] ndyi6 = -dyi6;
    wire signed [19:0] dyi7 = yi - A7;  wire signed [19:0] ndyi7 = -dyi7;
    wire [17:0] adi0 = dyi0[19] ? ndyi0[17:0] : dyi0[17:0];
    wire [17:0] adi1 = dyi1[19] ? ndyi1[17:0] : dyi1[17:0];
    wire [17:0] adi2 = dyi2[19] ? ndyi2[17:0] : dyi2[17:0];
    wire [17:0] adi3 = dyi3[19] ? ndyi3[17:0] : dyi3[17:0];
    wire [17:0] adi4 = dyi4[19] ? ndyi4[17:0] : dyi4[17:0];
    wire [17:0] adi5 = dyi5[19] ? ndyi5[17:0] : dyi5[17:0];
    wire [17:0] adi6 = dyi6[19] ? ndyi6[17:0] : dyi6[17:0];
    wire [17:0] adi7 = dyi7[19] ? ndyi7[17:0] : dyi7[17:0];
    wire signed [19:0] dyq0 = yq - A0;  wire signed [19:0] ndyq0 = -dyq0;
    wire signed [19:0] dyq1 = yq - A1;  wire signed [19:0] ndyq1 = -dyq1;
    wire signed [19:0] dyq2 = yq - A2;  wire signed [19:0] ndyq2 = -dyq2;
    wire signed [19:0] dyq3 = yq - A3;  wire signed [19:0] ndyq3 = -dyq3;
    wire signed [19:0] dyq4 = yq - A4;  wire signed [19:0] ndyq4 = -dyq4;
    wire signed [19:0] dyq5 = yq - A5;  wire signed [19:0] ndyq5 = -dyq5;
    wire signed [19:0] dyq6 = yq - A6;  wire signed [19:0] ndyq6 = -dyq6;
    wire signed [19:0] dyq7 = yq - A7;  wire signed [19:0] ndyq7 = -dyq7;
    wire [17:0] adq0 = dyq0[19] ? ndyq0[17:0] : dyq0[17:0];
    wire [17:0] adq1 = dyq1[19] ? ndyq1[17:0] : dyq1[17:0];
    wire [17:0] adq2 = dyq2[19] ? ndyq2[17:0] : dyq2[17:0];
    wire [17:0] adq3 = dyq3[19] ? ndyq3[17:0] : dyq3[17:0];
    wire [17:0] adq4 = dyq4[19] ? ndyq4[17:0] : dyq4[17:0];
    wire [17:0] adq5 = dyq5[19] ? ndyq5[17:0] : dyq5[17:0];
    wire [17:0] adq6 = dyq6[19] ? ndyq6[17:0] : dyq6[17:0];
    wire [17:0] adq7 = dyq7[19] ? ndyq7[17:0] : dyq7[17:0];
    // I 轴 bit0（S0=[0, 1, 2, 3] S1=[4, 5, 6, 7]）
    wire [17:0] d0_i0 = minu18(minu18(adi0, adi1), minu18(adi2, adi3));
    wire [17:0] d1_i0 = minu18(minu18(adi4, adi5), minu18(adi6, adi7));
    wire signed [18:0] dd_i0 = $signed({1'b0, d1_i0}) - $signed({1'b0, d0_i0});
    wire signed [18:0] ds_i0 = $signed({1'b0, d1_i0}) + $signed({1'b0, d0_i0});
    wire signed [37:0] pd_i0 = dd_i0 * ds_i0;
    wire signed [37:0] lq_i0 = pd_i0 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_i0 = (lq_i0 > 38'sd32767) ? 16'sd32767 : (lq_i0 < -38'sd32768) ? -16'sd32768 : lq_i0[15:0];
    // Q 轴 bit0（S0=[0, 1, 2, 3] S1=[4, 5, 6, 7]）
    wire [17:0] d0_q0 = minu18(minu18(adq0, adq1), minu18(adq2, adq3));
    wire [17:0] d1_q0 = minu18(minu18(adq4, adq5), minu18(adq6, adq7));
    wire signed [18:0] dd_q0 = $signed({1'b0, d1_q0}) - $signed({1'b0, d0_q0});
    wire signed [18:0] ds_q0 = $signed({1'b0, d1_q0}) + $signed({1'b0, d0_q0});
    wire signed [37:0] pd_q0 = dd_q0 * ds_q0;
    wire signed [37:0] lq_q0 = pd_q0 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_q0 = (lq_q0 > 38'sd32767) ? 16'sd32767 : (lq_q0 < -38'sd32768) ? -16'sd32768 : lq_q0[15:0];
    // I 轴 bit1（S0=[0, 1, 4, 5] S1=[2, 3, 6, 7]）
    wire [17:0] d0_i1 = minu18(minu18(adi0, adi1), minu18(adi4, adi5));
    wire [17:0] d1_i1 = minu18(minu18(adi2, adi3), minu18(adi6, adi7));
    wire signed [18:0] dd_i1 = $signed({1'b0, d1_i1}) - $signed({1'b0, d0_i1});
    wire signed [18:0] ds_i1 = $signed({1'b0, d1_i1}) + $signed({1'b0, d0_i1});
    wire signed [37:0] pd_i1 = dd_i1 * ds_i1;
    wire signed [37:0] lq_i1 = pd_i1 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_i1 = (lq_i1 > 38'sd32767) ? 16'sd32767 : (lq_i1 < -38'sd32768) ? -16'sd32768 : lq_i1[15:0];
    // Q 轴 bit1（S0=[0, 1, 4, 5] S1=[2, 3, 6, 7]）
    wire [17:0] d0_q1 = minu18(minu18(adq0, adq1), minu18(adq4, adq5));
    wire [17:0] d1_q1 = minu18(minu18(adq2, adq3), minu18(adq6, adq7));
    wire signed [18:0] dd_q1 = $signed({1'b0, d1_q1}) - $signed({1'b0, d0_q1});
    wire signed [18:0] ds_q1 = $signed({1'b0, d1_q1}) + $signed({1'b0, d0_q1});
    wire signed [37:0] pd_q1 = dd_q1 * ds_q1;
    wire signed [37:0] lq_q1 = pd_q1 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_q1 = (lq_q1 > 38'sd32767) ? 16'sd32767 : (lq_q1 < -38'sd32768) ? -16'sd32768 : lq_q1[15:0];
    // I 轴 bit2（S0=[0, 2, 4, 6] S1=[1, 3, 5, 7]）
    wire [17:0] d0_i2 = minu18(minu18(adi0, adi2), minu18(adi4, adi6));
    wire [17:0] d1_i2 = minu18(minu18(adi1, adi3), minu18(adi5, adi7));
    wire signed [18:0] dd_i2 = $signed({1'b0, d1_i2}) - $signed({1'b0, d0_i2});
    wire signed [18:0] ds_i2 = $signed({1'b0, d1_i2}) + $signed({1'b0, d0_i2});
    wire signed [37:0] pd_i2 = dd_i2 * ds_i2;
    wire signed [37:0] lq_i2 = pd_i2 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_i2 = (lq_i2 > 38'sd32767) ? 16'sd32767 : (lq_i2 < -38'sd32768) ? -16'sd32768 : lq_i2[15:0];
    // Q 轴 bit2（S0=[0, 2, 4, 6] S1=[1, 3, 5, 7]）
    wire [17:0] d0_q2 = minu18(minu18(adq0, adq2), minu18(adq4, adq6));
    wire [17:0] d1_q2 = minu18(minu18(adq1, adq3), minu18(adq5, adq7));
    wire signed [18:0] dd_q2 = $signed({1'b0, d1_q2}) - $signed({1'b0, d0_q2});
    wire signed [18:0] ds_q2 = $signed({1'b0, d1_q2}) + $signed({1'b0, d0_q2});
    wire signed [37:0] pd_q2 = dd_q2 * ds_q2;
    wire signed [37:0] lq_q2 = pd_q2 >>> 16;  // Q8.24 → Q8.8
    wire signed [15:0] llrv_q2 = (lq_q2 > 38'sd32767) ? 16'sd32767 : (lq_q2 < -38'sd32768) ? -16'sd32768 : lq_q2[15:0];

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            llr0 <= 16'sd0;
            llr1 <= 16'sd0;
            llr2 <= 16'sd0;
            llr3 <= 16'sd0;
            llr4 <= 16'sd0;
            llr5 <= 16'sd0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                llr0 <= llrv_i0;
                llr1 <= llrv_i1;
                llr2 <= llrv_i2;
                llr3 <= llrv_q0;
                llr4 <= llrv_q1;
                llr5 <= llrv_q2;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
