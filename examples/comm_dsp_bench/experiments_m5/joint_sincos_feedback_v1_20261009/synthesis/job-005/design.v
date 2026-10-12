// 参数化设计：QW-LUT N=64 order=linear
// 四分之一波折叠（16+2 项表），段内小数 10 位，线性除数 1024
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
    wire [5:0] mis = ms[15:10];
    wire [9:0] ds  = ms[9:0];
    wire [5:0] mic = mc[15:10];
    wire [9:0] dc  = mc[9:0];

    function signed [15:0] Tq;
        input [5:0] k;
        begin
            case (k)
            6'd0: Tq = 16'sd0;
            6'd1: Tq = 16'sd3212;
            6'd2: Tq = 16'sd6393;
            6'd3: Tq = 16'sd9512;
            6'd4: Tq = 16'sd12540;
            6'd5: Tq = 16'sd15447;
            6'd6: Tq = 16'sd18205;
            6'd7: Tq = 16'sd20788;
            6'd8: Tq = 16'sd23170;
            6'd9: Tq = 16'sd25330;
            6'd10: Tq = 16'sd27246;
            6'd11: Tq = 16'sd28899;
            6'd12: Tq = 16'sd30274;
            6'd13: Tq = 16'sd31357;
            6'd14: Tq = 16'sd32138;
            6'd15: Tq = 16'sd32610;
            6'd16: Tq = 16'sd32767;
            6'd17: Tq = 16'sd32610;
                default: Tq = 16'sd0;
            endcase
        end
    endfunction

    function signed [17:0] interpl;
        input [5:0] mi;
        input [9:0] d;
        reg signed [15:0] s0, s1;
        reg signed [16:0] a1;
        reg signed [28:0] lt;
        begin
            s0 = Tq(mi); s1 = Tq(mi + 6'd1);
            a1 = s1 - s0;
            lt = a1 * $signed({1'b0, d});
            interpl = s0 + $signed(lt[28:10]) + $signed({1'b0, lt[9]});
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
