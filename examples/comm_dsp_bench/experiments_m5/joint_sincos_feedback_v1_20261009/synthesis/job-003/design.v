// 参数化设计：QW-LUT N=256 order=linear
// 四分之一波折叠（64+2 项表），段内小数 8 位，线性除数 256
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
    wire [15:0] ps = z;
    wire [15:0] pc = z + 16'd16384;
    wire        ngs = ps[15];
    wire        ngc = pc[15];
    wire [14:0] prs = ps[14:0];
    wire [14:0] prc = pc[14:0];
    wire [15:0] ms = prs[14] ? (16'h8000 - {1'b0, prs}) : {1'b0, prs};
    wire [15:0] mc = prc[14] ? (16'h8000 - {1'b0, prc}) : {1'b0, prc};
    wire [7:0] mis = ms[15:8];
    wire [7:0] ds  = ms[7:0];
    wire [7:0] mic = mc[15:8];
    wire [7:0] dc  = mc[7:0];

    function signed [15:0] Tq;
        input [7:0] k;
        begin
            case (k)
            8'd0: Tq = 16'sd0;
            8'd1: Tq = 16'sd804;
            8'd2: Tq = 16'sd1608;
            8'd3: Tq = 16'sd2411;
            8'd4: Tq = 16'sd3212;
            8'd5: Tq = 16'sd4011;
            8'd6: Tq = 16'sd4808;
            8'd7: Tq = 16'sd5602;
            8'd8: Tq = 16'sd6393;
            8'd9: Tq = 16'sd7180;
            8'd10: Tq = 16'sd7962;
            8'd11: Tq = 16'sd8740;
            8'd12: Tq = 16'sd9512;
            8'd13: Tq = 16'sd10279;
            8'd14: Tq = 16'sd11039;
            8'd15: Tq = 16'sd11793;
            8'd16: Tq = 16'sd12540;
            8'd17: Tq = 16'sd13279;
            8'd18: Tq = 16'sd14010;
            8'd19: Tq = 16'sd14733;
            8'd20: Tq = 16'sd15447;
            8'd21: Tq = 16'sd16151;
            8'd22: Tq = 16'sd16846;
            8'd23: Tq = 16'sd17531;
            8'd24: Tq = 16'sd18205;
            8'd25: Tq = 16'sd18868;
            8'd26: Tq = 16'sd19520;
            8'd27: Tq = 16'sd20160;
            8'd28: Tq = 16'sd20788;
            8'd29: Tq = 16'sd21403;
            8'd30: Tq = 16'sd22006;
            8'd31: Tq = 16'sd22595;
            8'd32: Tq = 16'sd23170;
            8'd33: Tq = 16'sd23732;
            8'd34: Tq = 16'sd24279;
            8'd35: Tq = 16'sd24812;
            8'd36: Tq = 16'sd25330;
            8'd37: Tq = 16'sd25833;
            8'd38: Tq = 16'sd26320;
            8'd39: Tq = 16'sd26791;
            8'd40: Tq = 16'sd27246;
            8'd41: Tq = 16'sd27684;
            8'd42: Tq = 16'sd28106;
            8'd43: Tq = 16'sd28511;
            8'd44: Tq = 16'sd28899;
            8'd45: Tq = 16'sd29269;
            8'd46: Tq = 16'sd29622;
            8'd47: Tq = 16'sd29957;
            8'd48: Tq = 16'sd30274;
            8'd49: Tq = 16'sd30572;
            8'd50: Tq = 16'sd30853;
            8'd51: Tq = 16'sd31114;
            8'd52: Tq = 16'sd31357;
            8'd53: Tq = 16'sd31581;
            8'd54: Tq = 16'sd31786;
            8'd55: Tq = 16'sd31972;
            8'd56: Tq = 16'sd32138;
            8'd57: Tq = 16'sd32286;
            8'd58: Tq = 16'sd32413;
            8'd59: Tq = 16'sd32522;
            8'd60: Tq = 16'sd32610;
            8'd61: Tq = 16'sd32679;
            8'd62: Tq = 16'sd32729;
            8'd63: Tq = 16'sd32758;
            8'd64: Tq = 16'sd32767;
            8'd65: Tq = 16'sd32758;
                default: Tq = 16'sd0;
            endcase
        end
    endfunction

    function signed [17:0] interpl;
        input [7:0] mi;
        input [7:0] d;
        reg signed [15:0] s0, s1;
        reg signed [16:0] a1;
        reg signed [26:0] lt;
        begin
            s0 = Tq(mi); s1 = Tq(mi + 8'd1);
            a1 = s1 - s0;
            lt = a1 * $signed({1'b0, d});
            interpl = s0 + $signed(lt[26:8]) + $signed({1'b0, lt[7]});
        end
    endfunction

    wire signed [17:0] ys = interpl(mis, ds);
    wire signed [17:0] yc = interpl(mic, dc);
    wire signed [18:0] yss = ngs ? -ys : ys;
    wire signed [18:0] ycs = ngc ? -yc : yc;
    wire signed [15:0] sin_v = (yss > 19'sd32767) ? 16'sd32767 :
                               (yss < -19'sd32768) ? -16'sd32768 : yss[15:0];
    wire signed [15:0] cos_v = (ycs > 19'sd32767) ? 16'sd32767 :
                               (ycs < -19'sd32768) ? -16'sd32768 : ycs[15:0];

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            sin_out   <= 16'sd0;
            cos_out   <= 16'sd0;
        end else begin
            if (in_valid && in_ready) begin
                sin_out   <= sin_v;
                cos_out   <= cos_v;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
