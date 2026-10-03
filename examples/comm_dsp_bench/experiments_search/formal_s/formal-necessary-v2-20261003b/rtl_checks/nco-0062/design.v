// NCO 映射 nco=ir_d108e0d60a07
module nco_map (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [12:0] phase_w = phase_acc[31:19];
    wire [15:0] z_sin = {phase_w, {3{1'b0}}};
    wire [15:0] z_cos = z_sin + 16'd16384;
    // ---- 四分之一波 LUT + 插值 ----
    wire        ngs_s;
    wire [14:0] prs_s;
    wire [14:0] ms_s;
    wire [5:0] mi_s;
    wire [8:0] d_s;
    assign ngs_s = z_sin[15];
    assign prs_s = z_sin[14:0];
    wire [15:0] msf_s = 16'd32768 - {1'b0, prs_s};
    assign ms_s = prs_s[14] ? msf_s[14:0] : {1'b0, prs_s[13:0]};
    assign mi_s = ms_s >> 9;
    assign d_s = ms_s[8:0];
    reg signed [15:0] rom_s;
    always @(*) begin
        case (mi_s)
            6'd0: rom_s = 16'sd0;
            6'd1: rom_s = 16'sd1608;
            6'd2: rom_s = 16'sd3212;
            6'd3: rom_s = 16'sd4808;
            6'd4: rom_s = 16'sd6393;
            6'd5: rom_s = 16'sd7962;
            6'd6: rom_s = 16'sd9512;
            6'd7: rom_s = 16'sd11039;
            6'd8: rom_s = 16'sd12540;
            6'd9: rom_s = 16'sd14010;
            6'd10: rom_s = 16'sd15447;
            6'd11: rom_s = 16'sd16846;
            6'd12: rom_s = 16'sd18205;
            6'd13: rom_s = 16'sd19520;
            6'd14: rom_s = 16'sd20788;
            6'd15: rom_s = 16'sd22006;
            6'd16: rom_s = 16'sd23170;
            6'd17: rom_s = 16'sd24279;
            6'd18: rom_s = 16'sd25330;
            6'd19: rom_s = 16'sd26320;
            6'd20: rom_s = 16'sd27246;
            6'd21: rom_s = 16'sd28106;
            6'd22: rom_s = 16'sd28899;
            6'd23: rom_s = 16'sd29622;
            6'd24: rom_s = 16'sd30274;
            6'd25: rom_s = 16'sd30853;
            6'd26: rom_s = 16'sd31357;
            6'd27: rom_s = 16'sd31786;
            6'd28: rom_s = 16'sd32138;
            6'd29: rom_s = 16'sd32413;
            6'd30: rom_s = 16'sd32610;
            6'd31: rom_s = 16'sd32729;
            6'd32: rom_s = 16'sd32767;
            6'd33: rom_s = 16'sd32729;
            default: rom_s = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_s;
    always @(*) begin
        case (mi_s + 1)
            6'd0: rom1_s = 16'sd0;
            6'd1: rom1_s = 16'sd1608;
            6'd2: rom1_s = 16'sd3212;
            6'd3: rom1_s = 16'sd4808;
            6'd4: rom1_s = 16'sd6393;
            6'd5: rom1_s = 16'sd7962;
            6'd6: rom1_s = 16'sd9512;
            6'd7: rom1_s = 16'sd11039;
            6'd8: rom1_s = 16'sd12540;
            6'd9: rom1_s = 16'sd14010;
            6'd10: rom1_s = 16'sd15447;
            6'd11: rom1_s = 16'sd16846;
            6'd12: rom1_s = 16'sd18205;
            6'd13: rom1_s = 16'sd19520;
            6'd14: rom1_s = 16'sd20788;
            6'd15: rom1_s = 16'sd22006;
            6'd16: rom1_s = 16'sd23170;
            6'd17: rom1_s = 16'sd24279;
            6'd18: rom1_s = 16'sd25330;
            6'd19: rom1_s = 16'sd26320;
            6'd20: rom1_s = 16'sd27246;
            6'd21: rom1_s = 16'sd28106;
            6'd22: rom1_s = 16'sd28899;
            6'd23: rom1_s = 16'sd29622;
            6'd24: rom1_s = 16'sd30274;
            6'd25: rom1_s = 16'sd30853;
            6'd26: rom1_s = 16'sd31357;
            6'd27: rom1_s = 16'sd31786;
            6'd28: rom1_s = 16'sd32138;
            6'd29: rom1_s = 16'sd32413;
            6'd30: rom1_s = 16'sd32610;
            6'd31: rom1_s = 16'sd32729;
            6'd32: rom1_s = 16'sd32767;
            6'd33: rom1_s = 16'sd32729;
            default: rom1_s = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_s = rom1_s - rom_s;
    wire signed [25:0] lt_s = a1_s * {1'b0, d_s};
    wire signed [17:0] lr_s = {2'b0, rom_s} + (lt_s >>> 9) + {17'd0, (lt_s >>> 8) & 1'b1};
    wire signed [17:0] yw_s = lr_s;
    wire signed [17:0] yn_s = ngs_s ? -yw_s : yw_s;
    wire signed [15:0] out_s = (yn_s > 32767) ? 16'sd32767 : ((yn_s < -32768) ? -16'sd32768 : yn_s[15:0]);
    wire        ngs_c;
    wire [14:0] prs_c;
    wire [14:0] ms_c;
    wire [5:0] mi_c;
    wire [8:0] d_c;
    assign ngs_c = z_cos[15];
    assign prs_c = z_cos[14:0];
    wire [15:0] msf_c = 16'd32768 - {1'b0, prs_c};
    assign ms_c = prs_c[14] ? msf_c[14:0] : {1'b0, prs_c[13:0]};
    assign mi_c = ms_c >> 9;
    assign d_c = ms_c[8:0];
    reg signed [15:0] rom_c;
    always @(*) begin
        case (mi_c)
            6'd0: rom_c = 16'sd0;
            6'd1: rom_c = 16'sd1608;
            6'd2: rom_c = 16'sd3212;
            6'd3: rom_c = 16'sd4808;
            6'd4: rom_c = 16'sd6393;
            6'd5: rom_c = 16'sd7962;
            6'd6: rom_c = 16'sd9512;
            6'd7: rom_c = 16'sd11039;
            6'd8: rom_c = 16'sd12540;
            6'd9: rom_c = 16'sd14010;
            6'd10: rom_c = 16'sd15447;
            6'd11: rom_c = 16'sd16846;
            6'd12: rom_c = 16'sd18205;
            6'd13: rom_c = 16'sd19520;
            6'd14: rom_c = 16'sd20788;
            6'd15: rom_c = 16'sd22006;
            6'd16: rom_c = 16'sd23170;
            6'd17: rom_c = 16'sd24279;
            6'd18: rom_c = 16'sd25330;
            6'd19: rom_c = 16'sd26320;
            6'd20: rom_c = 16'sd27246;
            6'd21: rom_c = 16'sd28106;
            6'd22: rom_c = 16'sd28899;
            6'd23: rom_c = 16'sd29622;
            6'd24: rom_c = 16'sd30274;
            6'd25: rom_c = 16'sd30853;
            6'd26: rom_c = 16'sd31357;
            6'd27: rom_c = 16'sd31786;
            6'd28: rom_c = 16'sd32138;
            6'd29: rom_c = 16'sd32413;
            6'd30: rom_c = 16'sd32610;
            6'd31: rom_c = 16'sd32729;
            6'd32: rom_c = 16'sd32767;
            6'd33: rom_c = 16'sd32729;
            default: rom_c = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_c;
    always @(*) begin
        case (mi_c + 1)
            6'd0: rom1_c = 16'sd0;
            6'd1: rom1_c = 16'sd1608;
            6'd2: rom1_c = 16'sd3212;
            6'd3: rom1_c = 16'sd4808;
            6'd4: rom1_c = 16'sd6393;
            6'd5: rom1_c = 16'sd7962;
            6'd6: rom1_c = 16'sd9512;
            6'd7: rom1_c = 16'sd11039;
            6'd8: rom1_c = 16'sd12540;
            6'd9: rom1_c = 16'sd14010;
            6'd10: rom1_c = 16'sd15447;
            6'd11: rom1_c = 16'sd16846;
            6'd12: rom1_c = 16'sd18205;
            6'd13: rom1_c = 16'sd19520;
            6'd14: rom1_c = 16'sd20788;
            6'd15: rom1_c = 16'sd22006;
            6'd16: rom1_c = 16'sd23170;
            6'd17: rom1_c = 16'sd24279;
            6'd18: rom1_c = 16'sd25330;
            6'd19: rom1_c = 16'sd26320;
            6'd20: rom1_c = 16'sd27246;
            6'd21: rom1_c = 16'sd28106;
            6'd22: rom1_c = 16'sd28899;
            6'd23: rom1_c = 16'sd29622;
            6'd24: rom1_c = 16'sd30274;
            6'd25: rom1_c = 16'sd30853;
            6'd26: rom1_c = 16'sd31357;
            6'd27: rom1_c = 16'sd31786;
            6'd28: rom1_c = 16'sd32138;
            6'd29: rom1_c = 16'sd32413;
            6'd30: rom1_c = 16'sd32610;
            6'd31: rom1_c = 16'sd32729;
            6'd32: rom1_c = 16'sd32767;
            6'd33: rom1_c = 16'sd32729;
            default: rom1_c = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_c = rom1_c - rom_c;
    wire signed [25:0] lt_c = a1_c * {1'b0, d_c};
    wire signed [17:0] lr_c = {2'b0, rom_c} + (lt_c >>> 9) + {17'd0, (lt_c >>> 8) & 1'b1};
    wire signed [17:0] yw_c = lr_c;
    wire signed [17:0] yn_c = ngs_c ? -yw_c : yw_c;
    wire signed [15:0] out_c = (yn_c > 32767) ? 16'sd32767 : ((yn_c < -32768) ? -16'sd32768 : yn_c[15:0]);
    wire signed [15:0] nco_sin = out_s;
    wire signed [15:0] nco_cos = out_c;
    assign sin_o = nco_sin;
    assign cos_o = nco_cos;
endmodule
