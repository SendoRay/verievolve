// 参数化设计：QW-LUT N=128 order=quad
// 四分之一波折叠（32+2 项表），段内小数 9 位，线性除数 512
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
    wire [6:0] mis = ms[15:9];
    wire [8:0] ds  = ms[8:0];
    wire [6:0] mic = mc[15:9];
    wire [8:0] dc  = mc[8:0];

    function signed [15:0] Tq;
        input [6:0] k;
        begin
            case (k)
            7'd0: Tq = 16'sd0;
            7'd1: Tq = 16'sd1608;
            7'd2: Tq = 16'sd3212;
            7'd3: Tq = 16'sd4808;
            7'd4: Tq = 16'sd6393;
            7'd5: Tq = 16'sd7962;
            7'd6: Tq = 16'sd9512;
            7'd7: Tq = 16'sd11039;
            7'd8: Tq = 16'sd12540;
            7'd9: Tq = 16'sd14010;
            7'd10: Tq = 16'sd15447;
            7'd11: Tq = 16'sd16846;
            7'd12: Tq = 16'sd18205;
            7'd13: Tq = 16'sd19520;
            7'd14: Tq = 16'sd20788;
            7'd15: Tq = 16'sd22006;
            7'd16: Tq = 16'sd23170;
            7'd17: Tq = 16'sd24279;
            7'd18: Tq = 16'sd25330;
            7'd19: Tq = 16'sd26320;
            7'd20: Tq = 16'sd27246;
            7'd21: Tq = 16'sd28106;
            7'd22: Tq = 16'sd28899;
            7'd23: Tq = 16'sd29622;
            7'd24: Tq = 16'sd30274;
            7'd25: Tq = 16'sd30853;
            7'd26: Tq = 16'sd31357;
            7'd27: Tq = 16'sd31786;
            7'd28: Tq = 16'sd32138;
            7'd29: Tq = 16'sd32413;
            7'd30: Tq = 16'sd32610;
            7'd31: Tq = 16'sd32729;
            7'd32: Tq = 16'sd32767;
            7'd33: Tq = 16'sd32729;
                default: Tq = 16'sd0;
            endcase
        end
    endfunction

    function signed [18:0] interpq;
        input [6:0] mi;
        input [8:0] d;
        reg signed [15:0] s0, s1, s2;
        reg signed [16:0] a1;
        reg signed [17:0] a2;
        reg signed [27:0] lt;
        reg signed [16:0] lr;
        reg signed [9:0] d9, dm;
        reg signed [19:0] qw;
        reg signed [27:0] t2;
        reg signed [18:0] qr;
        begin
            s0 = Tq(mi); s1 = Tq(mi + 7'd1); s2 = Tq(mi + 7'd2);
            a1 = s1 - s0;
            a2 = s2 - 2*s1 + s0;
            d9 = $signed({1'b0, d});
            dm = d9 - 10'sd512;
            lt = a1 * d9;
            lr = $signed(lt[27:9]) + $signed({1'b0, lt[8]});
            qw = d9 * dm;
            t2 = $signed(a2[7:0]) * qw;
            qr = $signed(t2[27:19]) + $signed({1'b0, t2[18]});
            interpq = s0 + lr + qr;
        end
    endfunction

    wire signed [18:0] ys = interpq(mis, ds);
    wire signed [18:0] yc = interpq(mic, dc);
    wire signed [19:0] yss = ngs ? -ys : ys;
    wire signed [19:0] ycs = ngc ? -yc : yc;
    wire signed [15:0] sin_v = (yss > 20'sd32767) ? 16'sd32767 :
                               (yss < -20'sd32768) ? -16'sd32768 : yss[15:0];
    wire signed [15:0] cos_v = (ycs > 20'sd32767) ? 16'sd32767 :
                               (ycs < -20'sd32768) ? -16'sd32768 : ycs[15:0];

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
