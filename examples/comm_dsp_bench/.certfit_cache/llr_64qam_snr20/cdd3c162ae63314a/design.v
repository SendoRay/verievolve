// certfit 参数化 64QAM LLR：metric=l1 corr_entries=0 corr_frac=8 input_trunc=6
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output wire               out_dummy,
    output reg  signed [15:0] llr0,
    output reg  signed [15:0] llr1,
    output reg  signed [15:0] llr2,
    output reg  signed [15:0] llr3,
    output reg  signed [15:0] llr4,
    output reg  signed [15:0] llr5
);
    // EVOLVE-BLOCK-START
    function [10:0] uabs10;
        input signed [10:0] v;
        begin
            uabs10 = v < 0 ? -v : v;
        end
    endfunction
    function [17:0] dmin2;
        input [17:0] a, b;
        begin
            dmin2 = (a < b) ? a : b;
        end
    endfunction
    function [17:0] dmax2;
        input [17:0] a, b;
        begin
            dmax2 = (a > b) ? a : b;
        end
    endfunction
    wire signed [10:0] i_t = i_in >>> 6;
    wire signed [10:0] q_t = q_in >>> 6;
    wire [17:0] dI0 = uabs10($signed(i_t - 11'sd64));
    wire [17:0] dI1 = uabs10($signed(i_t - 11'sd192));
    wire [17:0] dI2 = uabs10($signed(i_t - 11'sd448));
    wire [17:0] dI3 = uabs10($signed(i_t - 11'sd320));
    wire [17:0] dI4 = uabs10($signed(i_t + 11'sd320));
    wire [17:0] dI5 = uabs10($signed(i_t + 11'sd448));
    wire [17:0] dI6 = uabs10($signed(i_t + 11'sd192));
    wire [17:0] dI7 = uabs10($signed(i_t + 11'sd64));
    wire [17:0] dQ0 = uabs10($signed(q_t - 11'sd64));
    wire [17:0] dQ1 = uabs10($signed(q_t - 11'sd192));
    wire [17:0] dQ2 = uabs10($signed(q_t - 11'sd448));
    wire [17:0] dQ3 = uabs10($signed(q_t - 11'sd320));
    wire [17:0] dQ4 = uabs10($signed(q_t + 11'sd320));
    wire [17:0] dQ5 = uabs10($signed(q_t + 11'sd448));
    wire [17:0] dQ6 = uabs10($signed(q_t + 11'sd192));
    wire [17:0] dQ7 = uabs10($signed(q_t + 11'sd64));


    wire [17:0] mq1 = dmin2(dQ0, dQ1);
    wire [17:0] mq1b = dmax2(dQ0, dQ1);
    wire [17:0] mq2 = dmin2(dQ2, dQ3);
    wire [17:0] mq2b = dmax2(dQ2, dQ3);
    wire [17:0] mq3 = dmin2(dQ4, dQ5);
    wire [17:0] mq3b = dmax2(dQ4, dQ5);
    wire [17:0] mq4 = dmin2(dQ6, dQ7);
    wire [17:0] mq4b = dmax2(dQ6, dQ7);
    wire [17:0] mqa = dmin2(mq1, mq2);
    wire [17:0] mqab = dmin2(mq1b, mq2b);
    wire [17:0] mqamax = dmax2(mq1, mq2);
    wire [17:0] mqb = dmin2(mq3, mq4);
    wire [17:0] mqbb = dmin2(mq3b, mq4b);
    wire [17:0] mqbmax = dmax2(mq3, mq4);
    wire [17:0] minQ = dmin2(mqa, mqb);
    wire [17:0] minQ2 = dmin2(mqab, dmin2(mqbb, mqamax));
    wire [17:0] mq1I = dmin2(dI0, dI1);
    wire [17:0] mq1Ib = dmax2(dI0, dI1);
    wire [17:0] mq2I = dmin2(dI2, dI3);
    wire [17:0] mq2Ib = dmax2(dI2, dI3);
    wire [17:0] mq3I = dmin2(dI4, dI5);
    wire [17:0] mq3Ib = dmax2(dI4, dI5);
    wire [17:0] mq4I = dmin2(dI6, dI7);
    wire [17:0] mq4Ib = dmax2(dI6, dI7);
    wire [17:0] mqaI = dmin2(mq1I, mq2I);
    wire [17:0] mqabI = dmin2(mq1Ib, mq2Ib);
    wire [17:0] mqamaxI = dmax2(mq1I, mq2I);
    wire [17:0] mqbI = dmin2(mq3I, mq4I);
    wire [17:0] mqbbI = dmin2(mq3Ib, mq4Ib);
    wire [17:0] mqbmaxI = dmax2(mq3I, mq4I);
    wire [17:0] minI = dmin2(mqaI, mqbI);
    wire [17:0] minI2 = dmin2(mqabI, dmin2(mqbbI, mqamaxI));
    wire [17:0] c0x1_dI0 = dmin2(dI0, dI1);
    wire [17:0] c0x1b_dI0 = dmax2(dI0, dI1);
    wire [17:0] c0x2_dI0 = dmin2(dI2, dI3);
    wire [17:0] c0x2b_dI0 = dmax2(dI2, dI3);
    wire [17:0] c0m_dI0 = dmin2(c0x1_dI0, c0x2_dI0);
    wire [17:0] c0m2_dI0 = dmin2(dmin2(c0x1b_dI0, c0x2b_dI0), dmax2(c0x1_dI0, c0x2_dI0));
    wire [17:0] c1x1_dI0 = dmin2(dI4, dI5);
    wire [17:0] c1x1b_dI0 = dmax2(dI4, dI5);
    wire [17:0] c1x2_dI0 = dmin2(dI6, dI7);
    wire [17:0] c1x2b_dI0 = dmax2(dI6, dI7);
    wire [17:0] c1m_dI0 = dmin2(c1x1_dI0, c1x2_dI0);
    wire [17:0] c1m2_dI0 = dmin2(dmin2(c1x1b_dI0, c1x2b_dI0), dmax2(c1x1_dI0, c1x2_dI0));
    wire [17:0] c0x1_dI1 = dmin2(dI0, dI1);
    wire [17:0] c0x1b_dI1 = dmax2(dI0, dI1);
    wire [17:0] c0x2_dI1 = dmin2(dI4, dI5);
    wire [17:0] c0x2b_dI1 = dmax2(dI4, dI5);
    wire [17:0] c0m_dI1 = dmin2(c0x1_dI1, c0x2_dI1);
    wire [17:0] c0m2_dI1 = dmin2(dmin2(c0x1b_dI1, c0x2b_dI1), dmax2(c0x1_dI1, c0x2_dI1));
    wire [17:0] c1x1_dI1 = dmin2(dI2, dI3);
    wire [17:0] c1x1b_dI1 = dmax2(dI2, dI3);
    wire [17:0] c1x2_dI1 = dmin2(dI6, dI7);
    wire [17:0] c1x2b_dI1 = dmax2(dI6, dI7);
    wire [17:0] c1m_dI1 = dmin2(c1x1_dI1, c1x2_dI1);
    wire [17:0] c1m2_dI1 = dmin2(dmin2(c1x1b_dI1, c1x2b_dI1), dmax2(c1x1_dI1, c1x2_dI1));
    wire [17:0] c0x1_dI2 = dmin2(dI0, dI2);
    wire [17:0] c0x1b_dI2 = dmax2(dI0, dI2);
    wire [17:0] c0x2_dI2 = dmin2(dI4, dI6);
    wire [17:0] c0x2b_dI2 = dmax2(dI4, dI6);
    wire [17:0] c0m_dI2 = dmin2(c0x1_dI2, c0x2_dI2);
    wire [17:0] c0m2_dI2 = dmin2(dmin2(c0x1b_dI2, c0x2b_dI2), dmax2(c0x1_dI2, c0x2_dI2));
    wire [17:0] c1x1_dI2 = dmin2(dI1, dI3);
    wire [17:0] c1x1b_dI2 = dmax2(dI1, dI3);
    wire [17:0] c1x2_dI2 = dmin2(dI5, dI7);
    wire [17:0] c1x2b_dI2 = dmax2(dI5, dI7);
    wire [17:0] c1m_dI2 = dmin2(c1x1_dI2, c1x2_dI2);
    wire [17:0] c1m2_dI2 = dmin2(dmin2(c1x1b_dI2, c1x2b_dI2), dmax2(c1x1_dI2, c1x2_dI2));
    wire [17:0] c0x1_dQ0 = dmin2(dQ0, dQ1);
    wire [17:0] c0x1b_dQ0 = dmax2(dQ0, dQ1);
    wire [17:0] c0x2_dQ0 = dmin2(dQ2, dQ3);
    wire [17:0] c0x2b_dQ0 = dmax2(dQ2, dQ3);
    wire [17:0] c0m_dQ0 = dmin2(c0x1_dQ0, c0x2_dQ0);
    wire [17:0] c0m2_dQ0 = dmin2(dmin2(c0x1b_dQ0, c0x2b_dQ0), dmax2(c0x1_dQ0, c0x2_dQ0));
    wire [17:0] c1x1_dQ0 = dmin2(dQ4, dQ5);
    wire [17:0] c1x1b_dQ0 = dmax2(dQ4, dQ5);
    wire [17:0] c1x2_dQ0 = dmin2(dQ6, dQ7);
    wire [17:0] c1x2b_dQ0 = dmax2(dQ6, dQ7);
    wire [17:0] c1m_dQ0 = dmin2(c1x1_dQ0, c1x2_dQ0);
    wire [17:0] c1m2_dQ0 = dmin2(dmin2(c1x1b_dQ0, c1x2b_dQ0), dmax2(c1x1_dQ0, c1x2_dQ0));
    wire [17:0] c0x1_dQ1 = dmin2(dQ0, dQ1);
    wire [17:0] c0x1b_dQ1 = dmax2(dQ0, dQ1);
    wire [17:0] c0x2_dQ1 = dmin2(dQ4, dQ5);
    wire [17:0] c0x2b_dQ1 = dmax2(dQ4, dQ5);
    wire [17:0] c0m_dQ1 = dmin2(c0x1_dQ1, c0x2_dQ1);
    wire [17:0] c0m2_dQ1 = dmin2(dmin2(c0x1b_dQ1, c0x2b_dQ1), dmax2(c0x1_dQ1, c0x2_dQ1));
    wire [17:0] c1x1_dQ1 = dmin2(dQ2, dQ3);
    wire [17:0] c1x1b_dQ1 = dmax2(dQ2, dQ3);
    wire [17:0] c1x2_dQ1 = dmin2(dQ6, dQ7);
    wire [17:0] c1x2b_dQ1 = dmax2(dQ6, dQ7);
    wire [17:0] c1m_dQ1 = dmin2(c1x1_dQ1, c1x2_dQ1);
    wire [17:0] c1m2_dQ1 = dmin2(dmin2(c1x1b_dQ1, c1x2b_dQ1), dmax2(c1x1_dQ1, c1x2_dQ1));
    wire [17:0] c0x1_dQ2 = dmin2(dQ0, dQ2);
    wire [17:0] c0x1b_dQ2 = dmax2(dQ0, dQ2);
    wire [17:0] c0x2_dQ2 = dmin2(dQ4, dQ6);
    wire [17:0] c0x2b_dQ2 = dmax2(dQ4, dQ6);
    wire [17:0] c0m_dQ2 = dmin2(c0x1_dQ2, c0x2_dQ2);
    wire [17:0] c0m2_dQ2 = dmin2(dmin2(c0x1b_dQ2, c0x2b_dQ2), dmax2(c0x1_dQ2, c0x2_dQ2));
    wire [17:0] c1x1_dQ2 = dmin2(dQ1, dQ3);
    wire [17:0] c1x1b_dQ2 = dmax2(dQ1, dQ3);
    wire [17:0] c1x2_dQ2 = dmin2(dQ5, dQ7);
    wire [17:0] c1x2b_dQ2 = dmax2(dQ5, dQ7);
    wire [17:0] c1m_dQ2 = dmin2(c1x1_dQ2, c1x2_dQ2);
    wire [17:0] c1m2_dQ2 = dmin2(dmin2(c1x1b_dQ2, c1x2b_dQ2), dmax2(c1x1_dQ2, c1x2_dQ2));
    wire [17:0] d0m_0 = c0m_dI0 + minQ;
    wire [17:0] d1m_0 = c1m_dI0 + minQ;
    wire signed [43:0] vq_0 = ($signed(d1m_0) - $signed(d0m_0)) >>> -2;
    wire signed [15:0] llr_0 = (vq_0 > 44'sd32767) ? 16'sd32767 :
                                 (vq_0 < -44'sd32768) ? -16'sd32768 : vq_0[15:0];
    wire [17:0] d0m_1 = c0m_dI1 + minQ;
    wire [17:0] d1m_1 = c1m_dI1 + minQ;
    wire signed [43:0] vq_1 = ($signed(d1m_1) - $signed(d0m_1)) >>> -2;
    wire signed [15:0] llr_1 = (vq_1 > 44'sd32767) ? 16'sd32767 :
                                 (vq_1 < -44'sd32768) ? -16'sd32768 : vq_1[15:0];
    wire [17:0] d0m_2 = c0m_dI2 + minQ;
    wire [17:0] d1m_2 = c1m_dI2 + minQ;
    wire signed [43:0] vq_2 = ($signed(d1m_2) - $signed(d0m_2)) >>> -2;
    wire signed [15:0] llr_2 = (vq_2 > 44'sd32767) ? 16'sd32767 :
                                 (vq_2 < -44'sd32768) ? -16'sd32768 : vq_2[15:0];
    wire [17:0] d0m_3 = c0m_dQ0 + minI;
    wire [17:0] d1m_3 = c1m_dQ0 + minI;
    wire signed [43:0] vq_3 = ($signed(d1m_3) - $signed(d0m_3)) >>> -2;
    wire signed [15:0] llr_3 = (vq_3 > 44'sd32767) ? 16'sd32767 :
                                 (vq_3 < -44'sd32768) ? -16'sd32768 : vq_3[15:0];
    wire [17:0] d0m_4 = c0m_dQ1 + minI;
    wire [17:0] d1m_4 = c1m_dQ1 + minI;
    wire signed [43:0] vq_4 = ($signed(d1m_4) - $signed(d0m_4)) >>> -2;
    wire signed [15:0] llr_4 = (vq_4 > 44'sd32767) ? 16'sd32767 :
                                 (vq_4 < -44'sd32768) ? -16'sd32768 : vq_4[15:0];
    wire [17:0] d0m_5 = c0m_dQ2 + minI;
    wire [17:0] d1m_5 = c1m_dQ2 + minI;
    wire signed [43:0] vq_5 = ($signed(d1m_5) - $signed(d0m_5)) >>> -2;
    wire signed [15:0] llr_5 = (vq_5 > 44'sd32767) ? 16'sd32767 :
                                 (vq_5 < -44'sd32768) ? -16'sd32768 : vq_5[15:0];
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
                llr0 <= llr_0;
            llr1 <= llr_1;
            llr2 <= llr_2;
            llr3 <= llr_3;
            llr4 <= llr_4;
            llr5 <= llr_5;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
