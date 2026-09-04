// CommDSP-Bench: cordic_sincos task — naive baseline
//
// 朴素实现：64 点全波查找表 + 最近邻采样（无插值），cos 相位偏移复用 sin 表。
// 该文件是进化的初始程序，EVOLVE-BLOCK 标记内的代码可被改写。

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
    // 朴素基线：64 点查找表，最近邻
    // z 的补码位型即全波相位（theta = z*pi/2^15）
    wire [15:0] phase = z;
    wire [5:0]  idx_s = phase[15:10];    // sin 相位索引
    wire [5:0]  idx_c = idx_s + 6'd16;   // cos = sin(x + pi/2)

    function signed [15:0] sin_lut;
        input [5:0] idx;
        begin
            case (idx)
            6'd0: sin_lut = 16'sd0;
            6'd1: sin_lut = 16'sd3212;
            6'd2: sin_lut = 16'sd6393;
            6'd3: sin_lut = 16'sd9512;
            6'd4: sin_lut = 16'sd12540;
            6'd5: sin_lut = 16'sd15447;
            6'd6: sin_lut = 16'sd18205;
            6'd7: sin_lut = 16'sd20788;
            6'd8: sin_lut = 16'sd23170;
            6'd9: sin_lut = 16'sd25330;
            6'd10: sin_lut = 16'sd27246;
            6'd11: sin_lut = 16'sd28899;
            6'd12: sin_lut = 16'sd30274;
            6'd13: sin_lut = 16'sd31357;
            6'd14: sin_lut = 16'sd32138;
            6'd15: sin_lut = 16'sd32610;
            6'd16: sin_lut = 16'sd32767;
            6'd17: sin_lut = 16'sd32610;
            6'd18: sin_lut = 16'sd32138;
            6'd19: sin_lut = 16'sd31357;
            6'd20: sin_lut = 16'sd30274;
            6'd21: sin_lut = 16'sd28899;
            6'd22: sin_lut = 16'sd27246;
            6'd23: sin_lut = 16'sd25330;
            6'd24: sin_lut = 16'sd23170;
            6'd25: sin_lut = 16'sd20788;
            6'd26: sin_lut = 16'sd18205;
            6'd27: sin_lut = 16'sd15447;
            6'd28: sin_lut = 16'sd12540;
            6'd29: sin_lut = 16'sd9512;
            6'd30: sin_lut = 16'sd6393;
            6'd31: sin_lut = 16'sd3212;
            6'd32: sin_lut = 16'sd0;
            6'd33: sin_lut = -16'sd3212;
            6'd34: sin_lut = -16'sd6393;
            6'd35: sin_lut = -16'sd9512;
            6'd36: sin_lut = -16'sd12540;
            6'd37: sin_lut = -16'sd15447;
            6'd38: sin_lut = -16'sd18205;
            6'd39: sin_lut = -16'sd20788;
            6'd40: sin_lut = -16'sd23170;
            6'd41: sin_lut = -16'sd25330;
            6'd42: sin_lut = -16'sd27246;
            6'd43: sin_lut = -16'sd28899;
            6'd44: sin_lut = -16'sd30274;
            6'd45: sin_lut = -16'sd31357;
            6'd46: sin_lut = -16'sd32138;
            6'd47: sin_lut = -16'sd32610;
            6'd48: sin_lut = -16'sd32767;
            6'd49: sin_lut = -16'sd32610;
            6'd50: sin_lut = -16'sd32138;
            6'd51: sin_lut = -16'sd31357;
            6'd52: sin_lut = -16'sd30274;
            6'd53: sin_lut = -16'sd28899;
            6'd54: sin_lut = -16'sd27246;
            6'd55: sin_lut = -16'sd25330;
            6'd56: sin_lut = -16'sd23170;
            6'd57: sin_lut = -16'sd20788;
            6'd58: sin_lut = -16'sd18205;
            6'd59: sin_lut = -16'sd15447;
            6'd60: sin_lut = -16'sd12540;
            6'd61: sin_lut = -16'sd9512;
            6'd62: sin_lut = -16'sd6393;
            6'd63: sin_lut = -16'sd3212;
                default: sin_lut = 16'sd0;
            endcase
        end
    endfunction

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            sin_out   <= 16'sd0;
            cos_out   <= 16'sd0;
        end else begin
            if (in_valid && in_ready) begin
                sin_out   <= sin_lut(idx_s);
                cos_out   <= sin_lut(idx_c);
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
