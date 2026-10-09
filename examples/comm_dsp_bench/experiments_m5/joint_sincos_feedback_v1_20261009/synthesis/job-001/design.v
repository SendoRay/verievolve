// 参数化设计：QW-LUT N=512 order=linear
// 四分之一波折叠（128+2 项表），段内小数 7 位，线性除数 128
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
    wire [8:0] mis = ms[15:7];
    wire [6:0] ds  = ms[6:0];
    wire [8:0] mic = mc[15:7];
    wire [6:0] dc  = mc[6:0];

    function signed [15:0] Tq;
        input [8:0] k;
        begin
            case (k)
            9'd0: Tq = 16'sd0;
            9'd1: Tq = 16'sd402;
            9'd2: Tq = 16'sd804;
            9'd3: Tq = 16'sd1206;
            9'd4: Tq = 16'sd1608;
            9'd5: Tq = 16'sd2009;
            9'd6: Tq = 16'sd2411;
            9'd7: Tq = 16'sd2811;
            9'd8: Tq = 16'sd3212;
            9'd9: Tq = 16'sd3612;
            9'd10: Tq = 16'sd4011;
            9'd11: Tq = 16'sd4410;
            9'd12: Tq = 16'sd4808;
            9'd13: Tq = 16'sd5205;
            9'd14: Tq = 16'sd5602;
            9'd15: Tq = 16'sd5998;
            9'd16: Tq = 16'sd6393;
            9'd17: Tq = 16'sd6787;
            9'd18: Tq = 16'sd7180;
            9'd19: Tq = 16'sd7571;
            9'd20: Tq = 16'sd7962;
            9'd21: Tq = 16'sd8351;
            9'd22: Tq = 16'sd8740;
            9'd23: Tq = 16'sd9127;
            9'd24: Tq = 16'sd9512;
            9'd25: Tq = 16'sd9896;
            9'd26: Tq = 16'sd10279;
            9'd27: Tq = 16'sd10660;
            9'd28: Tq = 16'sd11039;
            9'd29: Tq = 16'sd11417;
            9'd30: Tq = 16'sd11793;
            9'd31: Tq = 16'sd12167;
            9'd32: Tq = 16'sd12540;
            9'd33: Tq = 16'sd12910;
            9'd34: Tq = 16'sd13279;
            9'd35: Tq = 16'sd13646;
            9'd36: Tq = 16'sd14010;
            9'd37: Tq = 16'sd14373;
            9'd38: Tq = 16'sd14733;
            9'd39: Tq = 16'sd15091;
            9'd40: Tq = 16'sd15447;
            9'd41: Tq = 16'sd15800;
            9'd42: Tq = 16'sd16151;
            9'd43: Tq = 16'sd16500;
            9'd44: Tq = 16'sd16846;
            9'd45: Tq = 16'sd17190;
            9'd46: Tq = 16'sd17531;
            9'd47: Tq = 16'sd17869;
            9'd48: Tq = 16'sd18205;
            9'd49: Tq = 16'sd18538;
            9'd50: Tq = 16'sd18868;
            9'd51: Tq = 16'sd19195;
            9'd52: Tq = 16'sd19520;
            9'd53: Tq = 16'sd19841;
            9'd54: Tq = 16'sd20160;
            9'd55: Tq = 16'sd20475;
            9'd56: Tq = 16'sd20788;
            9'd57: Tq = 16'sd21097;
            9'd58: Tq = 16'sd21403;
            9'd59: Tq = 16'sd21706;
            9'd60: Tq = 16'sd22006;
            9'd61: Tq = 16'sd22302;
            9'd62: Tq = 16'sd22595;
            9'd63: Tq = 16'sd22884;
            9'd64: Tq = 16'sd23170;
            9'd65: Tq = 16'sd23453;
            9'd66: Tq = 16'sd23732;
            9'd67: Tq = 16'sd24008;
            9'd68: Tq = 16'sd24279;
            9'd69: Tq = 16'sd24548;
            9'd70: Tq = 16'sd24812;
            9'd71: Tq = 16'sd25073;
            9'd72: Tq = 16'sd25330;
            9'd73: Tq = 16'sd25583;
            9'd74: Tq = 16'sd25833;
            9'd75: Tq = 16'sd26078;
            9'd76: Tq = 16'sd26320;
            9'd77: Tq = 16'sd26557;
            9'd78: Tq = 16'sd26791;
            9'd79: Tq = 16'sd27020;
            9'd80: Tq = 16'sd27246;
            9'd81: Tq = 16'sd27467;
            9'd82: Tq = 16'sd27684;
            9'd83: Tq = 16'sd27897;
            9'd84: Tq = 16'sd28106;
            9'd85: Tq = 16'sd28311;
            9'd86: Tq = 16'sd28511;
            9'd87: Tq = 16'sd28707;
            9'd88: Tq = 16'sd28899;
            9'd89: Tq = 16'sd29086;
            9'd90: Tq = 16'sd29269;
            9'd91: Tq = 16'sd29448;
            9'd92: Tq = 16'sd29622;
            9'd93: Tq = 16'sd29792;
            9'd94: Tq = 16'sd29957;
            9'd95: Tq = 16'sd30118;
            9'd96: Tq = 16'sd30274;
            9'd97: Tq = 16'sd30425;
            9'd98: Tq = 16'sd30572;
            9'd99: Tq = 16'sd30715;
            9'd100: Tq = 16'sd30853;
            9'd101: Tq = 16'sd30986;
            9'd102: Tq = 16'sd31114;
            9'd103: Tq = 16'sd31238;
            9'd104: Tq = 16'sd31357;
            9'd105: Tq = 16'sd31471;
            9'd106: Tq = 16'sd31581;
            9'd107: Tq = 16'sd31686;
            9'd108: Tq = 16'sd31786;
            9'd109: Tq = 16'sd31881;
            9'd110: Tq = 16'sd31972;
            9'd111: Tq = 16'sd32058;
            9'd112: Tq = 16'sd32138;
            9'd113: Tq = 16'sd32214;
            9'd114: Tq = 16'sd32286;
            9'd115: Tq = 16'sd32352;
            9'd116: Tq = 16'sd32413;
            9'd117: Tq = 16'sd32470;
            9'd118: Tq = 16'sd32522;
            9'd119: Tq = 16'sd32568;
            9'd120: Tq = 16'sd32610;
            9'd121: Tq = 16'sd32647;
            9'd122: Tq = 16'sd32679;
            9'd123: Tq = 16'sd32706;
            9'd124: Tq = 16'sd32729;
            9'd125: Tq = 16'sd32746;
            9'd126: Tq = 16'sd32758;
            9'd127: Tq = 16'sd32766;
            9'd128: Tq = 16'sd32767;
            9'd129: Tq = 16'sd32766;
                default: Tq = 16'sd0;
            endcase
        end
    endfunction

    function signed [17:0] interpl;
        input [8:0] mi;
        input [6:0] d;
        reg signed [15:0] s0, s1;
        reg signed [16:0] a1;
        reg signed [25:0] lt;
        begin
            s0 = Tq(mi); s1 = Tq(mi + 9'd1);
            a1 = s1 - s0;
            lt = a1 * $signed({1'b0, d});
            interpl = s0 + $signed(lt[25:7]) + $signed({1'b0, lt[6]});
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
