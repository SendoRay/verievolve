// certfit 参数化 atan2：D=128 interp=linear div_frac=11
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] theta
);
    // EVOLVE-BLOCK-START
    wire [15:0] ai = i_in < 0 ? -i_in : i_in;
    wire [15:0] aq = q_in < 0 ? -q_in : q_in;
    wire swap = aq > ai;
    wire [15:0] x = swap ? aq : ai;
    wire [15:0] y = swap ? ai : aq;
    wire [15:0] xr = (x == 16'd0) ? 16'd1 : x;

    wire [26:0] yext = y;
    wire [26:0] num = yext << 11;
    wire [26:0] rq = num / xr;
    wire [26:0] rq_c = (rq > 26'd2047) ? 26'd2047 : rq;
    function signed [15:0] T;
        input [7:0] k;
        begin
            case (k)
                8'd0: T = 16'sd0;
                8'd1: T = 16'sd81;
                8'd2: T = 16'sd163;
                8'd3: T = 16'sd244;
                8'd4: T = 16'sd326;
                8'd5: T = 16'sd407;
                8'd6: T = 16'sd489;
                8'd7: T = 16'sd570;
                8'd8: T = 16'sd651;
                8'd9: T = 16'sd732;
                8'd10: T = 16'sd813;
                8'd11: T = 16'sd894;
                8'd12: T = 16'sd975;
                8'd13: T = 16'sd1056;
                8'd14: T = 16'sd1136;
                8'd15: T = 16'sd1217;
                8'd16: T = 16'sd1297;
                8'd17: T = 16'sd1377;
                8'd18: T = 16'sd1457;
                8'd19: T = 16'sd1537;
                8'd20: T = 16'sd1617;
                8'd21: T = 16'sd1696;
                8'd22: T = 16'sd1775;
                8'd23: T = 16'sd1854;
                8'd24: T = 16'sd1933;
                8'd25: T = 16'sd2012;
                8'd26: T = 16'sd2090;
                8'd27: T = 16'sd2168;
                8'd28: T = 16'sd2246;
                8'd29: T = 16'sd2324;
                8'd30: T = 16'sd2401;
                8'd31: T = 16'sd2478;
                8'd32: T = 16'sd2555;
                8'd33: T = 16'sd2632;
                8'd34: T = 16'sd2708;
                8'd35: T = 16'sd2784;
                8'd36: T = 16'sd2860;
                8'd37: T = 16'sd2935;
                8'd38: T = 16'sd3010;
                8'd39: T = 16'sd3085;
                8'd40: T = 16'sd3159;
                8'd41: T = 16'sd3233;
                8'd42: T = 16'sd3307;
                8'd43: T = 16'sd3380;
                8'd44: T = 16'sd3453;
                8'd45: T = 16'sd3526;
                8'd46: T = 16'sd3599;
                8'd47: T = 16'sd3670;
                8'd48: T = 16'sd3742;
                8'd49: T = 16'sd3813;
                8'd50: T = 16'sd3884;
                8'd51: T = 16'sd3955;
                8'd52: T = 16'sd4025;
                8'd53: T = 16'sd4095;
                8'd54: T = 16'sd4164;
                8'd55: T = 16'sd4233;
                8'd56: T = 16'sd4302;
                8'd57: T = 16'sd4370;
                8'd58: T = 16'sd4438;
                8'd59: T = 16'sd4505;
                8'd60: T = 16'sd4572;
                8'd61: T = 16'sd4639;
                8'd62: T = 16'sd4705;
                8'd63: T = 16'sd4771;
                8'd64: T = 16'sd4836;
                8'd65: T = 16'sd4901;
                8'd66: T = 16'sd4966;
                8'd67: T = 16'sd5030;
                8'd68: T = 16'sd5094;
                8'd69: T = 16'sd5157;
                8'd70: T = 16'sd5220;
                8'd71: T = 16'sd5282;
                8'd72: T = 16'sd5344;
                8'd73: T = 16'sd5406;
                8'd74: T = 16'sd5467;
                8'd75: T = 16'sd5528;
                8'd76: T = 16'sd5589;
                8'd77: T = 16'sd5649;
                8'd78: T = 16'sd5708;
                8'd79: T = 16'sd5768;
                8'd80: T = 16'sd5826;
                8'd81: T = 16'sd5885;
                8'd82: T = 16'sd5943;
                8'd83: T = 16'sd6000;
                8'd84: T = 16'sd6058;
                8'd85: T = 16'sd6114;
                8'd86: T = 16'sd6171;
                8'd87: T = 16'sd6227;
                8'd88: T = 16'sd6282;
                8'd89: T = 16'sd6337;
                8'd90: T = 16'sd6392;
                8'd91: T = 16'sd6446;
                8'd92: T = 16'sd6500;
                8'd93: T = 16'sd6554;
                8'd94: T = 16'sd6607;
                8'd95: T = 16'sd6660;
                8'd96: T = 16'sd6712;
                8'd97: T = 16'sd6764;
                8'd98: T = 16'sd6815;
                8'd99: T = 16'sd6867;
                8'd100: T = 16'sd6917;
                8'd101: T = 16'sd6968;
                8'd102: T = 16'sd7018;
                8'd103: T = 16'sd7068;
                8'd104: T = 16'sd7117;
                8'd105: T = 16'sd7166;
                8'd106: T = 16'sd7214;
                8'd107: T = 16'sd7262;
                8'd108: T = 16'sd7310;
                8'd109: T = 16'sd7358;
                8'd110: T = 16'sd7405;
                8'd111: T = 16'sd7451;
                8'd112: T = 16'sd7498;
                8'd113: T = 16'sd7544;
                8'd114: T = 16'sd7589;
                8'd115: T = 16'sd7635;
                8'd116: T = 16'sd7679;
                8'd117: T = 16'sd7724;
                8'd118: T = 16'sd7768;
                8'd119: T = 16'sd7812;
                8'd120: T = 16'sd7856;
                8'd121: T = 16'sd7899;
                8'd122: T = 16'sd7942;
                8'd123: T = 16'sd7984;
                8'd124: T = 16'sd8026;
                8'd125: T = 16'sd8068;
                8'd126: T = 16'sd8110;
                8'd127: T = 16'sd8151;
                8'd128: T = 16'sd8192;
                default: T = 16'sd0;
            endcase
        end
    endfunction
    wire [6:0] idx = rq_c[10:4];
    wire [3:0] frac = rq_c[3:0];
    wire signed [15:0] a0w = T(idx);
    wire signed [15:0] a1w = T(idx + 1'b1);
    wire signed [16 + 4:0] dd = (a1w - a0w) * $signed({1'b0, frac});
    wire signed [16 + 4:0] dqs = dd >>> 4;
    wire signed [16:0] a0w_x = a0w;
    wire signed [16:0] dqs_x = dqs;
    wire signed [16:0] a0 = a0w_x + dqs_x + $signed({16'd0, dd[3]});
    wire signed [16:0] base = swap ? (17'sd16384 - a0) : a0;
    wire signed [17:0] t1 = i_in[15] ? (18'sd32768 - base) : base;
    wire signed [17:0] t2 = q_in[15] ? -t1 : t1;
    wire signed [17:0] tw = (t2 >= 18'sd32768) ? (t2 - 18'sd65536) :
                            (t2 < -18'sd32768) ? (t2 + 18'sd65536) : t2;
    wire signed [15:0] result = tw[15:0];

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; theta <= 16'sd0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                theta <= result;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
