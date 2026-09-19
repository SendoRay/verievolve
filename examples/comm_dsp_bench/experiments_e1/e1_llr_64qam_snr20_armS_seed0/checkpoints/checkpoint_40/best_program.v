// 64QAM max-log LLR (v7): symmetric magnitude datapath (16x17 product),
// round-to-nearest scaling, shared pairwise-min tree over 8 PAM levels.
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
    // |y - lv| : y,lv are Q8.8 signed; result fits 16 bits unsigned
    function [15:0] adist;
        input signed [16:0] y;
        input signed [16:0] lv;
        reg signed [16:0] d;
        begin
            d = y - lv;
            adist = d[16] ? (~d[15:0] + 16'd1) : d[15:0];
        end
    endfunction

    function [15:0] mn;
        input [15:0] a;
        input [15:0] b;
        begin
            mn = (a < b) ? a : b;
        end
    endfunction

    // LLR = (d1^2 - d0^2) >>> 16, round-half-up on the SIGNED value, saturated.
    // |d1-d0| <= 61439 (16b), d1+d0 <= 122878 (17b) -> 16x17 product.
    // Taking pd = sign(d1-d0)*|d1-d0|*(d1+d0) = d1^2 - d0^2 exactly, then
    // (pd + 32768) >>> 16 with a signed reg performs round-half-up (arith shift),
    // matching the reference quantizer far better than magnitude rounding.
    function signed [15:0] lcalc;
        input [15:0] d0;
        input [15:0] d1;
        reg               neg;
        reg [15:0]        dda;
        reg [16:0]        ds;
        reg [32:0]        pr;
        reg signed [33:0] pd;
        reg signed [19:0] lq;
        begin
            neg = (d1 < d0);
            dda = neg ? (d0 - d1) : (d1 - d0);
            ds  = {1'b0, d1} + {1'b0, d0};
            pr  = dda * ds;
            pd  = neg ? -$signed({1'b0, pr}) : $signed({1'b0, pr});
            lq  = (pd + 34'sd32768) >>> 16;   // round half up (signed)
            lcalc = (lq > 20'sd32767)  ?  16'sd32767  :
                    (lq < -20'sd32768) ? -16'sd32768 : lq[15:0];
        end
    endfunction

    wire signed [16:0] yi = {i_in[15], i_in};
    wire signed [16:0] yq = {q_in[15], q_in};

    // distances to the 8 PAM levels (+-4096, +-12288, +-28672, +-20480)
    wire [15:0] ai0 = adist(yi,  17'sd4096);
    wire [15:0] ai1 = adist(yi,  17'sd12288);
    wire [15:0] ai2 = adist(yi,  17'sd28672);
    wire [15:0] ai3 = adist(yi,  17'sd20480);
    wire [15:0] ai4 = adist(yi, -17'sd20480);
    wire [15:0] ai5 = adist(yi, -17'sd28672);
    wire [15:0] ai6 = adist(yi, -17'sd12288);
    wire [15:0] ai7 = adist(yi, -17'sd4096);

    wire [15:0] aq0 = adist(yq,  17'sd4096);
    wire [15:0] aq1 = adist(yq,  17'sd12288);
    wire [15:0] aq2 = adist(yq,  17'sd28672);
    wire [15:0] aq3 = adist(yq,  17'sd20480);
    wire [15:0] aq4 = adist(yq, -17'sd20480);
    wire [15:0] aq5 = adist(yq, -17'sd28672);
    wire [15:0] aq6 = adist(yq, -17'sd12288);
    wire [15:0] aq7 = adist(yq, -17'sd4096);

    // shared pairwise minima (reused by all three bit-subsets)
    wire [15:0] ai01=mn(ai0,ai1), ai23=mn(ai2,ai3), ai45=mn(ai4,ai5), ai67=mn(ai6,ai7);
    wire [15:0] ai02=mn(ai0,ai2), ai13=mn(ai1,ai3), ai46=mn(ai4,ai6), ai57=mn(ai5,ai7);
    wire [15:0] aq01=mn(aq0,aq1), aq23=mn(aq2,aq3), aq45=mn(aq4,aq5), aq67=mn(aq6,aq7);
    wire [15:0] aq02=mn(aq0,aq2), aq13=mn(aq1,aq3), aq46=mn(aq4,aq6), aq57=mn(aq5,aq7);

    // I axis: bit0 S0={0,1,2,3}/S1={4,5,6,7}; bit1 S0={0,1,4,5}/S1={2,3,6,7};
    //         bit2 S0={0,2,4,6}/S1={1,3,5,7}
    wire signed [15:0] llrv_i0 = lcalc(mn(ai01,ai23), mn(ai45,ai67));
    wire signed [15:0] llrv_i1 = lcalc(mn(ai01,ai45), mn(ai23,ai67));
    wire signed [15:0] llrv_i2 = lcalc(mn(ai02,ai46), mn(ai13,ai57));
    // Q axis: same structure
    wire signed [15:0] llrv_q0 = lcalc(mn(aq01,aq23), mn(aq45,aq67));
    wire signed [15:0] llrv_q1 = lcalc(mn(aq01,aq45), mn(aq23,aq67));
    wire signed [15:0] llrv_q2 = lcalc(mn(aq02,aq46), mn(aq13,aq57));

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            llr0 <= 16'sd0; llr1 <= 16'sd0; llr2 <= 16'sd0;
            llr3 <= 16'sd0; llr4 <= 16'sd0; llr5 <= 16'sd0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                llr0 <= llrv_i0; llr1 <= llrv_i1; llr2 <= llrv_i2;
                llr3 <= llrv_q0; llr4 <= llrv_q1; llr5 <= llrv_q2;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule