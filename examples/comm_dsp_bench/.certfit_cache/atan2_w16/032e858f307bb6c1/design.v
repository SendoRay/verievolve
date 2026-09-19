// certfit 参数化 atan2：D=64 interp=linear div_frac=13
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

    wire [28:0] yext = y;
    wire [28:0] num = yext << 13;
    wire [28:0] rq = num / xr;
    wire [28:0] rq_c = (rq > 28'd8191) ? 28'd8191 : rq;
    function signed [15:0] T;
        input [6:0] k;
        begin
            case (k)
                7'd0: T = 16'sd0;
                7'd1: T = 16'sd163;
                7'd2: T = 16'sd326;
                7'd3: T = 16'sd489;
                7'd4: T = 16'sd651;
                7'd5: T = 16'sd813;
                7'd6: T = 16'sd975;
                7'd7: T = 16'sd1136;
                7'd8: T = 16'sd1297;
                7'd9: T = 16'sd1457;
                7'd10: T = 16'sd1617;
                7'd11: T = 16'sd1775;
                7'd12: T = 16'sd1933;
                7'd13: T = 16'sd2090;
                7'd14: T = 16'sd2246;
                7'd15: T = 16'sd2401;
                7'd16: T = 16'sd2555;
                7'd17: T = 16'sd2708;
                7'd18: T = 16'sd2860;
                7'd19: T = 16'sd3010;
                7'd20: T = 16'sd3159;
                7'd21: T = 16'sd3307;
                7'd22: T = 16'sd3453;
                7'd23: T = 16'sd3599;
                7'd24: T = 16'sd3742;
                7'd25: T = 16'sd3884;
                7'd26: T = 16'sd4025;
                7'd27: T = 16'sd4164;
                7'd28: T = 16'sd4302;
                7'd29: T = 16'sd4438;
                7'd30: T = 16'sd4572;
                7'd31: T = 16'sd4705;
                7'd32: T = 16'sd4836;
                7'd33: T = 16'sd4966;
                7'd34: T = 16'sd5094;
                7'd35: T = 16'sd5220;
                7'd36: T = 16'sd5344;
                7'd37: T = 16'sd5467;
                7'd38: T = 16'sd5589;
                7'd39: T = 16'sd5708;
                7'd40: T = 16'sd5826;
                7'd41: T = 16'sd5943;
                7'd42: T = 16'sd6058;
                7'd43: T = 16'sd6171;
                7'd44: T = 16'sd6282;
                7'd45: T = 16'sd6392;
                7'd46: T = 16'sd6500;
                7'd47: T = 16'sd6607;
                7'd48: T = 16'sd6712;
                7'd49: T = 16'sd6815;
                7'd50: T = 16'sd6917;
                7'd51: T = 16'sd7018;
                7'd52: T = 16'sd7117;
                7'd53: T = 16'sd7214;
                7'd54: T = 16'sd7310;
                7'd55: T = 16'sd7405;
                7'd56: T = 16'sd7498;
                7'd57: T = 16'sd7589;
                7'd58: T = 16'sd7679;
                7'd59: T = 16'sd7768;
                7'd60: T = 16'sd7856;
                7'd61: T = 16'sd7942;
                7'd62: T = 16'sd8026;
                7'd63: T = 16'sd8110;
                7'd64: T = 16'sd8192;
                default: T = 16'sd0;
            endcase
        end
    endfunction
    wire [5:0] idx = rq_c[12:7];
    wire [6:0] frac = rq_c[6:0];
    wire signed [15:0] a0w = T(idx);
    wire signed [15:0] a1w = T(idx + 1'b1);
    wire signed [16 + 7:0] dd = (a1w - a0w) * $signed({1'b0, frac});
    wire signed [16 + 7:0] dqs = dd >>> 7;
    wire signed [16:0] a0w_x = a0w;
    wire signed [16:0] dqs_x = dqs;
    wire signed [16:0] a0 = a0w_x + dqs_x + $signed({16'd0, dd[6]});
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
