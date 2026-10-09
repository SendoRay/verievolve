// 参数化设计：QW-LUT N=1024 order=linear
// 四分之一波折叠（256+2 项表），段内小数 6 位，线性除数 64
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
    wire [9:0] mis = ms[15:6];
    wire [5:0] ds  = ms[5:0];
    wire [9:0] mic = mc[15:6];
    wire [5:0] dc  = mc[5:0];

    function signed [15:0] Tq;
        input [9:0] k;
        begin
            case (k)
            10'd0: Tq = 16'sd0;
            10'd1: Tq = 16'sd201;
            10'd2: Tq = 16'sd402;
            10'd3: Tq = 16'sd603;
            10'd4: Tq = 16'sd804;
            10'd5: Tq = 16'sd1005;
            10'd6: Tq = 16'sd1206;
            10'd7: Tq = 16'sd1407;
            10'd8: Tq = 16'sd1608;
            10'd9: Tq = 16'sd1809;
            10'd10: Tq = 16'sd2009;
            10'd11: Tq = 16'sd2210;
            10'd12: Tq = 16'sd2411;
            10'd13: Tq = 16'sd2611;
            10'd14: Tq = 16'sd2811;
            10'd15: Tq = 16'sd3012;
            10'd16: Tq = 16'sd3212;
            10'd17: Tq = 16'sd3412;
            10'd18: Tq = 16'sd3612;
            10'd19: Tq = 16'sd3812;
            10'd20: Tq = 16'sd4011;
            10'd21: Tq = 16'sd4211;
            10'd22: Tq = 16'sd4410;
            10'd23: Tq = 16'sd4609;
            10'd24: Tq = 16'sd4808;
            10'd25: Tq = 16'sd5007;
            10'd26: Tq = 16'sd5205;
            10'd27: Tq = 16'sd5404;
            10'd28: Tq = 16'sd5602;
            10'd29: Tq = 16'sd5800;
            10'd30: Tq = 16'sd5998;
            10'd31: Tq = 16'sd6195;
            10'd32: Tq = 16'sd6393;
            10'd33: Tq = 16'sd6590;
            10'd34: Tq = 16'sd6787;
            10'd35: Tq = 16'sd6983;
            10'd36: Tq = 16'sd7180;
            10'd37: Tq = 16'sd7376;
            10'd38: Tq = 16'sd7571;
            10'd39: Tq = 16'sd7767;
            10'd40: Tq = 16'sd7962;
            10'd41: Tq = 16'sd8157;
            10'd42: Tq = 16'sd8351;
            10'd43: Tq = 16'sd8546;
            10'd44: Tq = 16'sd8740;
            10'd45: Tq = 16'sd8933;
            10'd46: Tq = 16'sd9127;
            10'd47: Tq = 16'sd9319;
            10'd48: Tq = 16'sd9512;
            10'd49: Tq = 16'sd9704;
            10'd50: Tq = 16'sd9896;
            10'd51: Tq = 16'sd10088;
            10'd52: Tq = 16'sd10279;
            10'd53: Tq = 16'sd10469;
            10'd54: Tq = 16'sd10660;
            10'd55: Tq = 16'sd10850;
            10'd56: Tq = 16'sd11039;
            10'd57: Tq = 16'sd11228;
            10'd58: Tq = 16'sd11417;
            10'd59: Tq = 16'sd11605;
            10'd60: Tq = 16'sd11793;
            10'd61: Tq = 16'sd11980;
            10'd62: Tq = 16'sd12167;
            10'd63: Tq = 16'sd12354;
            10'd64: Tq = 16'sd12540;
            10'd65: Tq = 16'sd12725;
            10'd66: Tq = 16'sd12910;
            10'd67: Tq = 16'sd13095;
            10'd68: Tq = 16'sd13279;
            10'd69: Tq = 16'sd13463;
            10'd70: Tq = 16'sd13646;
            10'd71: Tq = 16'sd13828;
            10'd72: Tq = 16'sd14010;
            10'd73: Tq = 16'sd14192;
            10'd74: Tq = 16'sd14373;
            10'd75: Tq = 16'sd14553;
            10'd76: Tq = 16'sd14733;
            10'd77: Tq = 16'sd14912;
            10'd78: Tq = 16'sd15091;
            10'd79: Tq = 16'sd15269;
            10'd80: Tq = 16'sd15447;
            10'd81: Tq = 16'sd15624;
            10'd82: Tq = 16'sd15800;
            10'd83: Tq = 16'sd15976;
            10'd84: Tq = 16'sd16151;
            10'd85: Tq = 16'sd16326;
            10'd86: Tq = 16'sd16500;
            10'd87: Tq = 16'sd16673;
            10'd88: Tq = 16'sd16846;
            10'd89: Tq = 16'sd17018;
            10'd90: Tq = 16'sd17190;
            10'd91: Tq = 16'sd17361;
            10'd92: Tq = 16'sd17531;
            10'd93: Tq = 16'sd17700;
            10'd94: Tq = 16'sd17869;
            10'd95: Tq = 16'sd18037;
            10'd96: Tq = 16'sd18205;
            10'd97: Tq = 16'sd18372;
            10'd98: Tq = 16'sd18538;
            10'd99: Tq = 16'sd18703;
            10'd100: Tq = 16'sd18868;
            10'd101: Tq = 16'sd19032;
            10'd102: Tq = 16'sd19195;
            10'd103: Tq = 16'sd19358;
            10'd104: Tq = 16'sd19520;
            10'd105: Tq = 16'sd19681;
            10'd106: Tq = 16'sd19841;
            10'd107: Tq = 16'sd20001;
            10'd108: Tq = 16'sd20160;
            10'd109: Tq = 16'sd20318;
            10'd110: Tq = 16'sd20475;
            10'd111: Tq = 16'sd20632;
            10'd112: Tq = 16'sd20788;
            10'd113: Tq = 16'sd20943;
            10'd114: Tq = 16'sd21097;
            10'd115: Tq = 16'sd21251;
            10'd116: Tq = 16'sd21403;
            10'd117: Tq = 16'sd21555;
            10'd118: Tq = 16'sd21706;
            10'd119: Tq = 16'sd21856;
            10'd120: Tq = 16'sd22006;
            10'd121: Tq = 16'sd22154;
            10'd122: Tq = 16'sd22302;
            10'd123: Tq = 16'sd22449;
            10'd124: Tq = 16'sd22595;
            10'd125: Tq = 16'sd22740;
            10'd126: Tq = 16'sd22884;
            10'd127: Tq = 16'sd23028;
            10'd128: Tq = 16'sd23170;
            10'd129: Tq = 16'sd23312;
            10'd130: Tq = 16'sd23453;
            10'd131: Tq = 16'sd23593;
            10'd132: Tq = 16'sd23732;
            10'd133: Tq = 16'sd23870;
            10'd134: Tq = 16'sd24008;
            10'd135: Tq = 16'sd24144;
            10'd136: Tq = 16'sd24279;
            10'd137: Tq = 16'sd24414;
            10'd138: Tq = 16'sd24548;
            10'd139: Tq = 16'sd24680;
            10'd140: Tq = 16'sd24812;
            10'd141: Tq = 16'sd24943;
            10'd142: Tq = 16'sd25073;
            10'd143: Tq = 16'sd25202;
            10'd144: Tq = 16'sd25330;
            10'd145: Tq = 16'sd25457;
            10'd146: Tq = 16'sd25583;
            10'd147: Tq = 16'sd25708;
            10'd148: Tq = 16'sd25833;
            10'd149: Tq = 16'sd25956;
            10'd150: Tq = 16'sd26078;
            10'd151: Tq = 16'sd26199;
            10'd152: Tq = 16'sd26320;
            10'd153: Tq = 16'sd26439;
            10'd154: Tq = 16'sd26557;
            10'd155: Tq = 16'sd26674;
            10'd156: Tq = 16'sd26791;
            10'd157: Tq = 16'sd26906;
            10'd158: Tq = 16'sd27020;
            10'd159: Tq = 16'sd27133;
            10'd160: Tq = 16'sd27246;
            10'd161: Tq = 16'sd27357;
            10'd162: Tq = 16'sd27467;
            10'd163: Tq = 16'sd27576;
            10'd164: Tq = 16'sd27684;
            10'd165: Tq = 16'sd27791;
            10'd166: Tq = 16'sd27897;
            10'd167: Tq = 16'sd28002;
            10'd168: Tq = 16'sd28106;
            10'd169: Tq = 16'sd28209;
            10'd170: Tq = 16'sd28311;
            10'd171: Tq = 16'sd28411;
            10'd172: Tq = 16'sd28511;
            10'd173: Tq = 16'sd28610;
            10'd174: Tq = 16'sd28707;
            10'd175: Tq = 16'sd28803;
            10'd176: Tq = 16'sd28899;
            10'd177: Tq = 16'sd28993;
            10'd178: Tq = 16'sd29086;
            10'd179: Tq = 16'sd29178;
            10'd180: Tq = 16'sd29269;
            10'd181: Tq = 16'sd29359;
            10'd182: Tq = 16'sd29448;
            10'd183: Tq = 16'sd29535;
            10'd184: Tq = 16'sd29622;
            10'd185: Tq = 16'sd29707;
            10'd186: Tq = 16'sd29792;
            10'd187: Tq = 16'sd29875;
            10'd188: Tq = 16'sd29957;
            10'd189: Tq = 16'sd30038;
            10'd190: Tq = 16'sd30118;
            10'd191: Tq = 16'sd30196;
            10'd192: Tq = 16'sd30274;
            10'd193: Tq = 16'sd30350;
            10'd194: Tq = 16'sd30425;
            10'd195: Tq = 16'sd30499;
            10'd196: Tq = 16'sd30572;
            10'd197: Tq = 16'sd30644;
            10'd198: Tq = 16'sd30715;
            10'd199: Tq = 16'sd30784;
            10'd200: Tq = 16'sd30853;
            10'd201: Tq = 16'sd30920;
            10'd202: Tq = 16'sd30986;
            10'd203: Tq = 16'sd31050;
            10'd204: Tq = 16'sd31114;
            10'd205: Tq = 16'sd31177;
            10'd206: Tq = 16'sd31238;
            10'd207: Tq = 16'sd31298;
            10'd208: Tq = 16'sd31357;
            10'd209: Tq = 16'sd31415;
            10'd210: Tq = 16'sd31471;
            10'd211: Tq = 16'sd31527;
            10'd212: Tq = 16'sd31581;
            10'd213: Tq = 16'sd31634;
            10'd214: Tq = 16'sd31686;
            10'd215: Tq = 16'sd31737;
            10'd216: Tq = 16'sd31786;
            10'd217: Tq = 16'sd31834;
            10'd218: Tq = 16'sd31881;
            10'd219: Tq = 16'sd31927;
            10'd220: Tq = 16'sd31972;
            10'd221: Tq = 16'sd32015;
            10'd222: Tq = 16'sd32058;
            10'd223: Tq = 16'sd32099;
            10'd224: Tq = 16'sd32138;
            10'd225: Tq = 16'sd32177;
            10'd226: Tq = 16'sd32214;
            10'd227: Tq = 16'sd32251;
            10'd228: Tq = 16'sd32286;
            10'd229: Tq = 16'sd32319;
            10'd230: Tq = 16'sd32352;
            10'd231: Tq = 16'sd32383;
            10'd232: Tq = 16'sd32413;
            10'd233: Tq = 16'sd32442;
            10'd234: Tq = 16'sd32470;
            10'd235: Tq = 16'sd32496;
            10'd236: Tq = 16'sd32522;
            10'd237: Tq = 16'sd32546;
            10'd238: Tq = 16'sd32568;
            10'd239: Tq = 16'sd32590;
            10'd240: Tq = 16'sd32610;
            10'd241: Tq = 16'sd32629;
            10'd242: Tq = 16'sd32647;
            10'd243: Tq = 16'sd32664;
            10'd244: Tq = 16'sd32679;
            10'd245: Tq = 16'sd32693;
            10'd246: Tq = 16'sd32706;
            10'd247: Tq = 16'sd32718;
            10'd248: Tq = 16'sd32729;
            10'd249: Tq = 16'sd32738;
            10'd250: Tq = 16'sd32746;
            10'd251: Tq = 16'sd32753;
            10'd252: Tq = 16'sd32758;
            10'd253: Tq = 16'sd32762;
            10'd254: Tq = 16'sd32766;
            10'd255: Tq = 16'sd32767;
            10'd256: Tq = 16'sd32767;
            10'd257: Tq = 16'sd32767;
                default: Tq = 16'sd0;
            endcase
        end
    endfunction

    function signed [17:0] interpl;
        input [9:0] mi;
        input [5:0] d;
        reg signed [15:0] s0, s1;
        reg signed [16:0] a1;
        reg signed [24:0] lt;
        begin
            s0 = Tq(mi); s1 = Tq(mi + 10'd1);
            a1 = s1 - s0;
            lt = a1 * $signed({1'b0, d});
            interpl = s0 + $signed(lt[24:6]) + $signed({1'b0, lt[5]});
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
