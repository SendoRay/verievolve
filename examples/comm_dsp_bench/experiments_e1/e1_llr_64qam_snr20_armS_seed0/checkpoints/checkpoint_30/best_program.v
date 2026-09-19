// 64QAM max-log LLR (v5): shared pairwise minima + round-to-nearest quantization,
// narrowed datapath (16-bit distances, 17x18 multipliers) and compact helper funcs.
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
    function [15:0] minu16;
        input [15:0] a;
        input [15:0] b;
        begin
            minu16 = (a < b) ? a : b;
        end
    endfunction

    // |y - lv|  (y,lv in Q8.8; result fits 16 bits unsigned)
    function [15:0] adist;
        input signed [16:0] y;
        input signed [16:0] lv;
        begin
            adist = (y >= lv) ? (y - lv) : (lv - y);
        end
    endfunction

    // LLR from the min-distances of the two subsets: (d1-d0)(d1+d0) = d1^2-d0^2
    // Round-to-nearest when scaling Q8.24 -> Q8.8
    function signed [15:0] llrf;
        input [15:0] a0;
        input [15:0] a1;
        reg signed [16:0] dd;
        reg signed [17:0] ds;
        reg signed [34:0] pd;
        reg signed [34:0] lq;
        begin
            dd = $signed({1'b0, a1}) - $signed({1'b0, a0});
            ds = $signed({2'b0, a1}) + $signed({2'b0, a0});
            pd = dd * ds;
            lq = (pd + 35'sd32768) >>> 16;   // round to nearest
            llrf = (lq > 35'sd32767) ? 16'sd32767 :
                   (lq < -35'sd32768) ? -16'sd32768 : lq[15:0];
        end
    endfunction

    wire signed [16:0] yi = {{1{i_in[15]}}, i_in};
    wire signed [16:0] yq = {{1{q_in[15]}}, q_in};

    // distances to the 8 PAM levels (+-4096, +-12288, +-28672, +-20480)
    wire [15:0] adi0 = adist(yi,  17'sd4096);
    wire [15:0] adi1 = adist(yi,  17'sd12288);
    wire [15:0] adi2 = adist(yi,  17'sd28672);
    wire [15:0] adi3 = adist(yi,  17'sd20480);
    wire [15:0] adi4 = adist(yi, -17'sd20480);
    wire [15:0] adi5 = adist(yi, -17'sd28672);
    wire [15:0] adi6 = adist(yi, -17'sd12288);
    wire [15:0] adi7 = adist(yi, -17'sd4096);

    wire [15:0] adq0 = adist(yq,  17'sd4096);
    wire [15:0] adq1 = adist(yq,  17'sd12288);
    wire [15:0] adq2 = adist(yq,  17'sd28672);
    wire [15:0] adq3 = adist(yq,  17'sd20480);
    wire [15:0] adq4 = adist(yq, -17'sd20480);
    wire [15:0] adq5 = adist(yq, -17'sd28672);
    wire [15:0] adq6 = adist(yq, -17'sd12288);
    wire [15:0] adq7 = adist(yq, -17'sd4096);

    // shared pairwise minima (reused by all three bit-subsets)
    wire [15:0] gi01 = minu16(adi0, adi1);
    wire [15:0] gi23 = minu16(adi2, adi3);
    wire [15:0] gi45 = minu16(adi4, adi5);
    wire [15:0] gi67 = minu16(adi6, adi7);
    wire [15:0] gi02 = minu16(adi0, adi2);
    wire [15:0] gi46 = minu16(adi4, adi6);
    wire [15:0] gi13 = minu16(adi1, adi3);
    wire [15:0] gi57 = minu16(adi5, adi7);

    wire [15:0] gq01 = minu16(adq0, adq1);
    wire [15:0] gq23 = minu16(adq2, adq3);
    wire [15:0] gq45 = minu16(adq4, adq5);
    wire [15:0] gq67 = minu16(adq6, adq7);
    wire [15:0] gq02 = minu16(adq0, adq2);
    wire [15:0] gq46 = minu16(adq4, adq6);
    wire [15:0] gq13 = minu16(adq1, adq3);
    wire [15:0] gq57 = minu16(adq5, adq7);

    // I axis: bit0 S0={0,1,2,3}/S1={4,5,6,7}; bit1 S0={0,1,4,5}/S1={2,3,6,7};
    //         bit2 S0={0,2,4,6}/S1={1,3,5,7}
    wire signed [15:0] llrv_i0 = llrf(minu16(gi01, gi23), minu16(gi45, gi67));
    wire signed [15:0] llrv_i1 = llrf(minu16(gi01, gi45), minu16(gi23, gi67));
    wire signed [15:0] llrv_i2 = llrf(minu16(gi02, gi46), minu16(gi13, gi57));
    // Q axis: same structure
    wire signed [15:0] llrv_q0 = llrf(minu16(gq01, gq23), minu16(gq45, gq67));
    wire signed [15:0] llrv_q1 = llrf(minu16(gq01, gq45), minu16(gq23, gq67));
    wire signed [15:0] llrv_q2 = llrf(minu16(gq02, gq46), minu16(gq13, gq57));

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