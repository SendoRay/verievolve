// CommDSP-Bench: cordic_sincos task — 1/4-wave LUT + symmetry + linear interp
//
// 改进实现：仅存 17 点 1/4 波表，利用 4 象限对称展开整波，再对相邻表项做
// 10-bit 线性插值。相比朴素最近邻（误差 O(h)），插值误差降到 O(h^2)，
// 精度大幅提升；同时 1/4 表把存储量降到原来的 ~1/4。

module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] z,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] sin_out,
    output reg  signed [15:0] cos_out
);

    // EVOLVE-BLOCK-START
    // 1/4 波正弦表（65 点，步长 1.40625°，0..90°）
    // 相比 33 点表，h 再减半，线性插值 O(h^2) 误差降到 1/4（约 +12 dB SQNR）。
    function signed [15:0] qt;
        input [6:0] k;
        begin
            case (k)
            7'd0:  qt = 16'sd0;
            7'd1:  qt = 16'sd804;
            7'd2:  qt = 16'sd1608;
            7'd3:  qt = 16'sd2411;
            7'd4:  qt = 16'sd3212;
            7'd5:  qt = 16'sd4012;
            7'd6:  qt = 16'sd4809;
            7'd7:  qt = 16'sd5603;
            7'd8:  qt = 16'sd6393;
            7'd9:  qt = 16'sd7179;
            7'd10: qt = 16'sd7962;
            7'd11: qt = 16'sd8741;
            7'd12: qt = 16'sd9513;
            7'd13: qt = 16'sd10280;
            7'd14: qt = 16'sd11040;
            7'd15: qt = 16'sd11794;
            7'd16: qt = 16'sd12540;
            7'd17: qt = 16'sd13279;
            7'd18: qt = 16'sd14011;
            7'd19: qt = 16'sd14734;
            7'd20: qt = 16'sd15446;
            7'd21: qt = 16'sd16151;
            7'd22: qt = 16'sd16846;
            7'd23: qt = 16'sd17530;
            7'd24: qt = 16'sd18205;
            7'd25: qt = 16'sd18868;
            7'd26: qt = 16'sd19520;
            7'd27: qt = 16'sd20160;
            7'd28: qt = 16'sd20786;
            7'd29: qt = 16'sd21402;
            7'd30: qt = 16'sd22004;
            7'd31: qt = 16'sd22592;
            7'd32: qt = 16'sd23170;
            7'd33: qt = 16'sd23729;
            7'd34: qt = 16'sd24277;
            7'd35: qt = 16'sd24812;
            7'd36: qt = 16'sd25330;
            7'd37: qt = 16'sd25832;
            7'd38: qt = 16'sd26319;
            7'd39: qt = 16'sd26788;
            7'd40: qt = 16'sd27245;
            7'd41: qt = 16'sd27683;
            7'd42: qt = 16'sd28103;
            7'd43: qt = 16'sd28500;
            7'd44: qt = 16'sd28896;
            7'd45: qt = 16'sd29276;
            7'd46: qt = 16'sd29625;
            7'd47: qt = 16'sd29960;
            7'd48: qt = 16'sd30271;
            7'd49: qt = 16'sd30561;
            7'd50: qt = 16'sd30856;
            7'd51: qt = 16'sd31105;
            7'd52: qt = 16'sd31351;
            7'd53: qt = 16'sd31579;
            7'd54: qt = 16'sd31782;
            7'd55: qt = 16'sd31968;
            7'd56: qt = 16'sd32134;
            7'd57: qt = 16'sd32281;
            7'd58: qt = 16'sd32409;
            7'd59: qt = 16'sd32518;
            7'd60: qt = 16'sd32606;
            7'd61: qt = 16'sd32675;
            7'd62: qt = 16'sd32725;
            7'd63: qt = 16'sd32754;
            7'd64: qt = 16'sd32767;
            default: qt = 16'sd0;
            endcase
        end
    endfunction

    // 由 8-bit 相位索引（整波 256 点）经对称性重建正弦值
    function signed [15:0] ft;
        input [7:0] i;
        reg [6:0] k;
        reg signed [15:0] v;
        begin
            k = i[6] ? (7'd64 - {1'b0, i[5:0]}) : {1'b0, i[5:0]};
            v = qt(k);
            ft = i[7] ? -v : v;
        end
    endfunction

    // 线性插值：base + (next-base)*frac / 256
    // d 只需容纳相邻表项之差（密集表中 |d| <= 804），用最小位宽避免综合出
    // 过宽的乘法器（d 为 12-bit，f 为 9-bit，乘积仅 21-bit）。
    function signed [15:0] ip;
        input [15:0] ph;
        reg signed [15:0]  b, n;
        reg signed [11:0]  d;
        reg signed [21:0]  p;
        reg signed [8:0]   f;
        begin
            b = ft(ph[15:8]);
            n = ft(ph[15:8] + 8'd1);       // 8-bit 自然回绕
            f = $signed({1'b0, ph[7:0]});
            d = n - b;
            p = d * f;
            ip = b + ((p + 22'sd128) >>> 8);    // 四舍五入
        end
    endfunction

    wire signed [15:0] sin_w = ip(z);
    wire signed [15:0] cos_w = ip(z + 16'd16384);   // cos(x)=sin(x+pi/2)

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            sin_out   <= 16'sd0;
            cos_out   <= 16'sd0;
        end else begin
            if (in_valid && in_ready) begin
                sin_out   <= sin_w;
                cos_out   <= cos_w;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule