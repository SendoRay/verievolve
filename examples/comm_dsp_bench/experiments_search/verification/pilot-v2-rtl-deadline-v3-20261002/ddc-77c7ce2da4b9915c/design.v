// Complete DDC generated from search IR 77c7ce2da4b9915c0503b8094d31e08f823d4d2c668b6516cd82e4a2cc32a151
module top (
    input  wire clk,
    input  wire rst_n,
    input  wire in_valid,
    output wire in_ready,
    input  wire [31:0] fcw,
    input  wire signed [11:0] i_in,
    input  wire signed [11:0] q_in,
    output wire signed [15:0] y_re,
    output wire signed [15:0] y_im,
    output wire out_valid,
    input  wire out_ready
);
    reg [31:0] phase_acc;
    always @(posedge clk) begin
        if (!rst_n)
            phase_acc <= 32'd0;
        else if (in_valid && in_ready)
            phase_acc <= phase_acc + fcw;
    end

    wire signed [15:0] nco_sin, nco_cos;
    nco_map u_nco (
        .phase_acc(phase_acc), .sin_o(nco_sin), .cos_o(nco_cos)
    );

    wire signed [27:0] prod_ic = $signed(i_in) * $signed(nco_cos);
    wire signed [27:0] prod_qs = $signed(q_in) * $signed(nco_sin);
    wire signed [27:0] prod_is = $signed(i_in) * $signed(nco_sin);
    wire signed [27:0] prod_qc = $signed(q_in) * $signed(nco_cos);
    wire signed [28:0] mix_re_pre =
        {prod_ic[27], prod_ic} + {prod_qs[27], prod_qs};
    wire signed [28:0] mix_im_pre =
        {prod_qc[27], prod_qc} - {prod_is[27], prod_is};
    wire signed [28:0] mix_re_shift = (mix_re_pre + 29'sd1024) >>> 11;
    wire signed [28:0] mix_im_shift = (mix_im_pre + 29'sd1024) >>> 11;
    wire signed [15:0] mix_re = (mix_re_shift > 32767) ? 16'sd32767 :
        ((mix_re_shift < -32768) ? -16'sd32768 : mix_re_shift[15:0]);
    wire signed [15:0] mix_im = (mix_im_shift > 32767) ? 16'sd32767 :
        ((mix_im_shift < -32768) ? -16'sd32768 : mix_im_shift[15:0]);

    fir_decimator u_fir (
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
        .x_re(mix_re), .x_im(mix_im),
        .y_re(y_re), .y_im(y_im), .out_valid(out_valid), .out_ready(out_ready)
    );
endmodule

// Generic phasor composition from search IR
module nco_map (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [31:0] phase_rounded = phase_acc + 32'h00800000;
    wire [31:0] coarse_acc = {phase_rounded[31:24], {24{1'b0}}};
    wire [31:0] residual_acc = phase_acc - coarse_acc;

    wire signed [15:0] coarse_sin, coarse_cos;
    wire signed [15:0] residual_sin, residual_cos;
    nco_leaf_7ea40bb92e38 u_coarse (
        .phase_acc(coarse_acc), .sin_o(coarse_sin), .cos_o(coarse_cos)
    );
    nco_leaf_7e411fa352e6 u_residual (
        .phase_acc(residual_acc), .sin_o(residual_sin), .cos_o(residual_cos)
    );

    wire signed [31:0] prod_cc = coarse_cos * residual_cos;
    wire signed [31:0] prod_ss = coarse_sin * residual_sin;
    wire signed [31:0] prod_sc = coarse_sin * residual_cos;
    wire signed [31:0] prod_cs = coarse_cos * residual_sin;
    wire signed [32:0] real_pre = {prod_cc[31], prod_cc} - {prod_ss[31], prod_ss};
    wire signed [32:0] imag_pre = {prod_sc[31], prod_sc} + {prod_cs[31], prod_cs};
    wire signed [32:0] real_q = (real_pre + 33'sd16384) >>> 15;
    wire signed [32:0] imag_q = (imag_pre + 33'sd16384) >>> 15;
    assign cos_o = (real_q > 32767) ? 16'sd32767 :
                   ((real_q < -32768) ? -16'sd32768 : real_q[15:0]);
    assign sin_o = (imag_q > 32767) ? 16'sd32767 :
                   ((imag_q < -32768) ? -16'sd32768 : imag_q[15:0]);
endmodule

// NCO 映射 nco=ir_7ea40bb92e38
module nco_leaf_7ea40bb92e38 (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [15:0] phase_w = phase_acc[31:16];
    wire [15:0] z_sin = {phase_w, {0{1'b0}}};
    wire [15:0] z_cos = z_sin + 16'd16384;
    // ---- 四分之一波 LUT + 插值 ----
    wire        ngs_s;
    wire [14:0] prs_s;
    wire [14:0] ms_s;
    wire [6:0] mi_s;
    wire [7:0] d_s;
    assign ngs_s = z_sin[15];
    assign prs_s = z_sin[14:0];
    wire [15:0] msf_s = 16'd32768 - {1'b0, prs_s};
    assign ms_s = prs_s[14] ? msf_s[14:0] : {1'b0, prs_s[13:0]};
    assign mi_s = ms_s >> 8;
    assign d_s = ms_s[7:0];
    reg signed [15:0] rom_s;
    always @(*) begin
        case (mi_s)
            7'd0: rom_s = 16'sd0;
            7'd1: rom_s = 16'sd804;
            7'd2: rom_s = 16'sd1608;
            7'd3: rom_s = 16'sd2411;
            7'd4: rom_s = 16'sd3212;
            7'd5: rom_s = 16'sd4011;
            7'd6: rom_s = 16'sd4808;
            7'd7: rom_s = 16'sd5602;
            7'd8: rom_s = 16'sd6393;
            7'd9: rom_s = 16'sd7180;
            7'd10: rom_s = 16'sd7962;
            7'd11: rom_s = 16'sd8740;
            7'd12: rom_s = 16'sd9512;
            7'd13: rom_s = 16'sd10279;
            7'd14: rom_s = 16'sd11039;
            7'd15: rom_s = 16'sd11793;
            7'd16: rom_s = 16'sd12540;
            7'd17: rom_s = 16'sd13279;
            7'd18: rom_s = 16'sd14010;
            7'd19: rom_s = 16'sd14733;
            7'd20: rom_s = 16'sd15447;
            7'd21: rom_s = 16'sd16151;
            7'd22: rom_s = 16'sd16846;
            7'd23: rom_s = 16'sd17531;
            7'd24: rom_s = 16'sd18205;
            7'd25: rom_s = 16'sd18868;
            7'd26: rom_s = 16'sd19520;
            7'd27: rom_s = 16'sd20160;
            7'd28: rom_s = 16'sd20788;
            7'd29: rom_s = 16'sd21403;
            7'd30: rom_s = 16'sd22006;
            7'd31: rom_s = 16'sd22595;
            7'd32: rom_s = 16'sd23170;
            7'd33: rom_s = 16'sd23732;
            7'd34: rom_s = 16'sd24279;
            7'd35: rom_s = 16'sd24812;
            7'd36: rom_s = 16'sd25330;
            7'd37: rom_s = 16'sd25833;
            7'd38: rom_s = 16'sd26320;
            7'd39: rom_s = 16'sd26791;
            7'd40: rom_s = 16'sd27246;
            7'd41: rom_s = 16'sd27684;
            7'd42: rom_s = 16'sd28106;
            7'd43: rom_s = 16'sd28511;
            7'd44: rom_s = 16'sd28899;
            7'd45: rom_s = 16'sd29269;
            7'd46: rom_s = 16'sd29622;
            7'd47: rom_s = 16'sd29957;
            7'd48: rom_s = 16'sd30274;
            7'd49: rom_s = 16'sd30572;
            7'd50: rom_s = 16'sd30853;
            7'd51: rom_s = 16'sd31114;
            7'd52: rom_s = 16'sd31357;
            7'd53: rom_s = 16'sd31581;
            7'd54: rom_s = 16'sd31786;
            7'd55: rom_s = 16'sd31972;
            7'd56: rom_s = 16'sd32138;
            7'd57: rom_s = 16'sd32286;
            7'd58: rom_s = 16'sd32413;
            7'd59: rom_s = 16'sd32522;
            7'd60: rom_s = 16'sd32610;
            7'd61: rom_s = 16'sd32679;
            7'd62: rom_s = 16'sd32729;
            7'd63: rom_s = 16'sd32758;
            7'd64: rom_s = 16'sd32767;
            7'd65: rom_s = 16'sd32758;
            default: rom_s = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_s;
    always @(*) begin
        case (mi_s + 1)
            7'd0: rom1_s = 16'sd0;
            7'd1: rom1_s = 16'sd804;
            7'd2: rom1_s = 16'sd1608;
            7'd3: rom1_s = 16'sd2411;
            7'd4: rom1_s = 16'sd3212;
            7'd5: rom1_s = 16'sd4011;
            7'd6: rom1_s = 16'sd4808;
            7'd7: rom1_s = 16'sd5602;
            7'd8: rom1_s = 16'sd6393;
            7'd9: rom1_s = 16'sd7180;
            7'd10: rom1_s = 16'sd7962;
            7'd11: rom1_s = 16'sd8740;
            7'd12: rom1_s = 16'sd9512;
            7'd13: rom1_s = 16'sd10279;
            7'd14: rom1_s = 16'sd11039;
            7'd15: rom1_s = 16'sd11793;
            7'd16: rom1_s = 16'sd12540;
            7'd17: rom1_s = 16'sd13279;
            7'd18: rom1_s = 16'sd14010;
            7'd19: rom1_s = 16'sd14733;
            7'd20: rom1_s = 16'sd15447;
            7'd21: rom1_s = 16'sd16151;
            7'd22: rom1_s = 16'sd16846;
            7'd23: rom1_s = 16'sd17531;
            7'd24: rom1_s = 16'sd18205;
            7'd25: rom1_s = 16'sd18868;
            7'd26: rom1_s = 16'sd19520;
            7'd27: rom1_s = 16'sd20160;
            7'd28: rom1_s = 16'sd20788;
            7'd29: rom1_s = 16'sd21403;
            7'd30: rom1_s = 16'sd22006;
            7'd31: rom1_s = 16'sd22595;
            7'd32: rom1_s = 16'sd23170;
            7'd33: rom1_s = 16'sd23732;
            7'd34: rom1_s = 16'sd24279;
            7'd35: rom1_s = 16'sd24812;
            7'd36: rom1_s = 16'sd25330;
            7'd37: rom1_s = 16'sd25833;
            7'd38: rom1_s = 16'sd26320;
            7'd39: rom1_s = 16'sd26791;
            7'd40: rom1_s = 16'sd27246;
            7'd41: rom1_s = 16'sd27684;
            7'd42: rom1_s = 16'sd28106;
            7'd43: rom1_s = 16'sd28511;
            7'd44: rom1_s = 16'sd28899;
            7'd45: rom1_s = 16'sd29269;
            7'd46: rom1_s = 16'sd29622;
            7'd47: rom1_s = 16'sd29957;
            7'd48: rom1_s = 16'sd30274;
            7'd49: rom1_s = 16'sd30572;
            7'd50: rom1_s = 16'sd30853;
            7'd51: rom1_s = 16'sd31114;
            7'd52: rom1_s = 16'sd31357;
            7'd53: rom1_s = 16'sd31581;
            7'd54: rom1_s = 16'sd31786;
            7'd55: rom1_s = 16'sd31972;
            7'd56: rom1_s = 16'sd32138;
            7'd57: rom1_s = 16'sd32286;
            7'd58: rom1_s = 16'sd32413;
            7'd59: rom1_s = 16'sd32522;
            7'd60: rom1_s = 16'sd32610;
            7'd61: rom1_s = 16'sd32679;
            7'd62: rom1_s = 16'sd32729;
            7'd63: rom1_s = 16'sd32758;
            7'd64: rom1_s = 16'sd32767;
            7'd65: rom1_s = 16'sd32758;
            default: rom1_s = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_s = rom1_s - rom_s;
    wire signed [24:0] lt_s = a1_s * {1'b0, d_s};
    wire signed [17:0] lr_s = {2'b0, rom_s} + (lt_s >>> 8) + {17'd0, (lt_s >>> 7) & 1'b1};
    wire signed [17:0] yw_s = lr_s;
    wire signed [17:0] yn_s = ngs_s ? -yw_s : yw_s;
    wire signed [15:0] out_s = (yn_s > 32767) ? 16'sd32767 : ((yn_s < -32768) ? -16'sd32768 : yn_s[15:0]);
    wire        ngs_c;
    wire [14:0] prs_c;
    wire [14:0] ms_c;
    wire [6:0] mi_c;
    wire [7:0] d_c;
    assign ngs_c = z_cos[15];
    assign prs_c = z_cos[14:0];
    wire [15:0] msf_c = 16'd32768 - {1'b0, prs_c};
    assign ms_c = prs_c[14] ? msf_c[14:0] : {1'b0, prs_c[13:0]};
    assign mi_c = ms_c >> 8;
    assign d_c = ms_c[7:0];
    reg signed [15:0] rom_c;
    always @(*) begin
        case (mi_c)
            7'd0: rom_c = 16'sd0;
            7'd1: rom_c = 16'sd804;
            7'd2: rom_c = 16'sd1608;
            7'd3: rom_c = 16'sd2411;
            7'd4: rom_c = 16'sd3212;
            7'd5: rom_c = 16'sd4011;
            7'd6: rom_c = 16'sd4808;
            7'd7: rom_c = 16'sd5602;
            7'd8: rom_c = 16'sd6393;
            7'd9: rom_c = 16'sd7180;
            7'd10: rom_c = 16'sd7962;
            7'd11: rom_c = 16'sd8740;
            7'd12: rom_c = 16'sd9512;
            7'd13: rom_c = 16'sd10279;
            7'd14: rom_c = 16'sd11039;
            7'd15: rom_c = 16'sd11793;
            7'd16: rom_c = 16'sd12540;
            7'd17: rom_c = 16'sd13279;
            7'd18: rom_c = 16'sd14010;
            7'd19: rom_c = 16'sd14733;
            7'd20: rom_c = 16'sd15447;
            7'd21: rom_c = 16'sd16151;
            7'd22: rom_c = 16'sd16846;
            7'd23: rom_c = 16'sd17531;
            7'd24: rom_c = 16'sd18205;
            7'd25: rom_c = 16'sd18868;
            7'd26: rom_c = 16'sd19520;
            7'd27: rom_c = 16'sd20160;
            7'd28: rom_c = 16'sd20788;
            7'd29: rom_c = 16'sd21403;
            7'd30: rom_c = 16'sd22006;
            7'd31: rom_c = 16'sd22595;
            7'd32: rom_c = 16'sd23170;
            7'd33: rom_c = 16'sd23732;
            7'd34: rom_c = 16'sd24279;
            7'd35: rom_c = 16'sd24812;
            7'd36: rom_c = 16'sd25330;
            7'd37: rom_c = 16'sd25833;
            7'd38: rom_c = 16'sd26320;
            7'd39: rom_c = 16'sd26791;
            7'd40: rom_c = 16'sd27246;
            7'd41: rom_c = 16'sd27684;
            7'd42: rom_c = 16'sd28106;
            7'd43: rom_c = 16'sd28511;
            7'd44: rom_c = 16'sd28899;
            7'd45: rom_c = 16'sd29269;
            7'd46: rom_c = 16'sd29622;
            7'd47: rom_c = 16'sd29957;
            7'd48: rom_c = 16'sd30274;
            7'd49: rom_c = 16'sd30572;
            7'd50: rom_c = 16'sd30853;
            7'd51: rom_c = 16'sd31114;
            7'd52: rom_c = 16'sd31357;
            7'd53: rom_c = 16'sd31581;
            7'd54: rom_c = 16'sd31786;
            7'd55: rom_c = 16'sd31972;
            7'd56: rom_c = 16'sd32138;
            7'd57: rom_c = 16'sd32286;
            7'd58: rom_c = 16'sd32413;
            7'd59: rom_c = 16'sd32522;
            7'd60: rom_c = 16'sd32610;
            7'd61: rom_c = 16'sd32679;
            7'd62: rom_c = 16'sd32729;
            7'd63: rom_c = 16'sd32758;
            7'd64: rom_c = 16'sd32767;
            7'd65: rom_c = 16'sd32758;
            default: rom_c = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_c;
    always @(*) begin
        case (mi_c + 1)
            7'd0: rom1_c = 16'sd0;
            7'd1: rom1_c = 16'sd804;
            7'd2: rom1_c = 16'sd1608;
            7'd3: rom1_c = 16'sd2411;
            7'd4: rom1_c = 16'sd3212;
            7'd5: rom1_c = 16'sd4011;
            7'd6: rom1_c = 16'sd4808;
            7'd7: rom1_c = 16'sd5602;
            7'd8: rom1_c = 16'sd6393;
            7'd9: rom1_c = 16'sd7180;
            7'd10: rom1_c = 16'sd7962;
            7'd11: rom1_c = 16'sd8740;
            7'd12: rom1_c = 16'sd9512;
            7'd13: rom1_c = 16'sd10279;
            7'd14: rom1_c = 16'sd11039;
            7'd15: rom1_c = 16'sd11793;
            7'd16: rom1_c = 16'sd12540;
            7'd17: rom1_c = 16'sd13279;
            7'd18: rom1_c = 16'sd14010;
            7'd19: rom1_c = 16'sd14733;
            7'd20: rom1_c = 16'sd15447;
            7'd21: rom1_c = 16'sd16151;
            7'd22: rom1_c = 16'sd16846;
            7'd23: rom1_c = 16'sd17531;
            7'd24: rom1_c = 16'sd18205;
            7'd25: rom1_c = 16'sd18868;
            7'd26: rom1_c = 16'sd19520;
            7'd27: rom1_c = 16'sd20160;
            7'd28: rom1_c = 16'sd20788;
            7'd29: rom1_c = 16'sd21403;
            7'd30: rom1_c = 16'sd22006;
            7'd31: rom1_c = 16'sd22595;
            7'd32: rom1_c = 16'sd23170;
            7'd33: rom1_c = 16'sd23732;
            7'd34: rom1_c = 16'sd24279;
            7'd35: rom1_c = 16'sd24812;
            7'd36: rom1_c = 16'sd25330;
            7'd37: rom1_c = 16'sd25833;
            7'd38: rom1_c = 16'sd26320;
            7'd39: rom1_c = 16'sd26791;
            7'd40: rom1_c = 16'sd27246;
            7'd41: rom1_c = 16'sd27684;
            7'd42: rom1_c = 16'sd28106;
            7'd43: rom1_c = 16'sd28511;
            7'd44: rom1_c = 16'sd28899;
            7'd45: rom1_c = 16'sd29269;
            7'd46: rom1_c = 16'sd29622;
            7'd47: rom1_c = 16'sd29957;
            7'd48: rom1_c = 16'sd30274;
            7'd49: rom1_c = 16'sd30572;
            7'd50: rom1_c = 16'sd30853;
            7'd51: rom1_c = 16'sd31114;
            7'd52: rom1_c = 16'sd31357;
            7'd53: rom1_c = 16'sd31581;
            7'd54: rom1_c = 16'sd31786;
            7'd55: rom1_c = 16'sd31972;
            7'd56: rom1_c = 16'sd32138;
            7'd57: rom1_c = 16'sd32286;
            7'd58: rom1_c = 16'sd32413;
            7'd59: rom1_c = 16'sd32522;
            7'd60: rom1_c = 16'sd32610;
            7'd61: rom1_c = 16'sd32679;
            7'd62: rom1_c = 16'sd32729;
            7'd63: rom1_c = 16'sd32758;
            7'd64: rom1_c = 16'sd32767;
            7'd65: rom1_c = 16'sd32758;
            default: rom1_c = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_c = rom1_c - rom_c;
    wire signed [24:0] lt_c = a1_c * {1'b0, d_c};
    wire signed [17:0] lr_c = {2'b0, rom_c} + (lt_c >>> 8) + {17'd0, (lt_c >>> 7) & 1'b1};
    wire signed [17:0] yw_c = lr_c;
    wire signed [17:0] yn_c = ngs_c ? -yw_c : yw_c;
    wire signed [15:0] out_c = (yn_c > 32767) ? 16'sd32767 : ((yn_c < -32768) ? -16'sd32768 : yn_c[15:0]);
    wire signed [15:0] nco_sin = out_s;
    wire signed [15:0] nco_cos = out_c;
    assign sin_o = nco_sin;
    assign cos_o = nco_cos;
endmodule

// NCO 映射 nco=ir_7e411fa352e6
module nco_leaf_7e411fa352e6 (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [15:0] phase_w = phase_acc[31:16];
    wire [15:0] z16 = {phase_w, {0{1'b0}}};
    // ---- 展开 CORDIC（za0 = 8·z mod 2^18；x/y 19 位自然回绕）----
    // 相位码转有符号域（s = z16 的 16 位补码值），与 Python 侧一致
    wire signed [16:0] s_w = $signed(z16);
    wire signed [17:0] z2 = $signed({z16, 1'b0});    // 2s（17 位符号保持）
    wire        hi_c = (s_w > 17'sd16384);            // 严格大于（16384 不折叠，对拍校准）
    wire        lo_c = (s_w < -17'sd16384);
    wire signed [17:0] z_0 = hi_c ? (z2 - 18'sd65536) : (lo_c ? (z2 + 18'sd65536) : z2);
    wire        neg_c = hi_c | lo_c;
    wire signed [18:0] x_0 = 19'sd79594;
    wire signed [18:0] y_0 = 19'sd0;
    wire        zp0 = z_0[17];
    wire signed [18:0] x_1 = zp0 ? (x_0 + (y_0 >>> 0)) : (x_0 - (y_0 >>> 0));
    wire signed [18:0] y_1 = zp0 ? (y_0 - (x_0 >>> 0)) : (y_0 + (x_0 >>> 0));
    wire signed [17:0] z_1 = zp0 ? (z_0 + 18'sd16384) : (z_0 - 18'sd16384);
    wire        zp1 = z_1[17];
    wire signed [18:0] x_2 = zp1 ? (x_1 + (y_1 >>> 1)) : (x_1 - (y_1 >>> 1));
    wire signed [18:0] y_2 = zp1 ? (y_1 - (x_1 >>> 1)) : (y_1 + (x_1 >>> 1));
    wire signed [17:0] z_2 = zp1 ? (z_1 + 18'sd9672) : (z_1 - 18'sd9672);
    wire        zp2 = z_2[17];
    wire signed [18:0] x_3 = zp2 ? (x_2 + (y_2 >>> 2)) : (x_2 - (y_2 >>> 2));
    wire signed [18:0] y_3 = zp2 ? (y_2 - (x_2 >>> 2)) : (y_2 + (x_2 >>> 2));
    wire signed [17:0] z_3 = zp2 ? (z_2 + 18'sd5110) : (z_2 - 18'sd5110);
    wire        zp3 = z_3[17];
    wire signed [18:0] x_4 = zp3 ? (x_3 + (y_3 >>> 3)) : (x_3 - (y_3 >>> 3));
    wire signed [18:0] y_4 = zp3 ? (y_3 - (x_3 >>> 3)) : (y_3 + (x_3 >>> 3));
    wire signed [17:0] z_4 = zp3 ? (z_3 + 18'sd2594) : (z_3 - 18'sd2594);
    wire        zp4 = z_4[17];
    wire signed [18:0] x_5 = zp4 ? (x_4 + (y_4 >>> 4)) : (x_4 - (y_4 >>> 4));
    wire signed [18:0] y_5 = zp4 ? (y_4 - (x_4 >>> 4)) : (y_4 + (x_4 >>> 4));
    wire signed [17:0] z_5 = zp4 ? (z_4 + 18'sd1302) : (z_4 - 18'sd1302);
    wire        zp5 = z_5[17];
    wire signed [18:0] x_6 = zp5 ? (x_5 + (y_5 >>> 5)) : (x_5 - (y_5 >>> 5));
    wire signed [18:0] y_6 = zp5 ? (y_5 - (x_5 >>> 5)) : (y_5 + (x_5 >>> 5));
    wire signed [17:0] z_6 = zp5 ? (z_5 + 18'sd652) : (z_5 - 18'sd652);
    wire        zp6 = z_6[17];
    wire signed [18:0] x_7 = zp6 ? (x_6 + (y_6 >>> 6)) : (x_6 - (y_6 >>> 6));
    wire signed [18:0] y_7 = zp6 ? (y_6 - (x_6 >>> 6)) : (y_6 + (x_6 >>> 6));
    wire signed [17:0] z_7 = zp6 ? (z_6 + 18'sd326) : (z_6 - 18'sd326);
    wire        zp7 = z_7[17];
    wire signed [18:0] x_8 = zp7 ? (x_7 + (y_7 >>> 7)) : (x_7 - (y_7 >>> 7));
    wire signed [18:0] y_8 = zp7 ? (y_7 - (x_7 >>> 7)) : (y_7 + (x_7 >>> 7));
    wire signed [17:0] z_8 = zp7 ? (z_7 + 18'sd163) : (z_7 - 18'sd163);
    wire        zp8 = z_8[17];
    wire signed [18:0] x_9 = zp8 ? (x_8 + (y_8 >>> 8)) : (x_8 - (y_8 >>> 8));
    wire signed [18:0] y_9 = zp8 ? (y_8 - (x_8 >>> 8)) : (y_8 + (x_8 >>> 8));
    wire signed [17:0] z_9 = zp8 ? (z_8 + 18'sd81) : (z_8 - 18'sd81);
    wire        zp9 = z_9[17];
    wire signed [18:0] x_10 = zp9 ? (x_9 + (y_9 >>> 9)) : (x_9 - (y_9 >>> 9));
    wire signed [18:0] y_10 = zp9 ? (y_9 - (x_9 >>> 9)) : (y_9 + (x_9 >>> 9));
    wire signed [17:0] z_10 = zp9 ? (z_9 + 18'sd41) : (z_9 - 18'sd41);
    wire        zp10 = z_10[17];
    wire signed [18:0] x_11 = zp10 ? (x_10 + (y_10 >>> 10)) : (x_10 - (y_10 >>> 10));
    wire signed [18:0] y_11 = zp10 ? (y_10 - (x_10 >>> 10)) : (y_10 + (x_10 >>> 10));
    wire signed [17:0] z_11 = zp10 ? (z_10 + 18'sd20) : (z_10 - 18'sd20);
    wire        zp11 = z_11[17];
    wire signed [18:0] x_12 = zp11 ? (x_11 + (y_11 >>> 11)) : (x_11 - (y_11 >>> 11));
    wire signed [18:0] y_12 = zp11 ? (y_11 - (x_11 >>> 11)) : (y_11 + (x_11 >>> 11));
    wire signed [17:0] z_12 = zp11 ? (z_11 + 18'sd10) : (z_11 - 18'sd10);
    wire signed [18:0] sin_r = (y_12 + 19'sd2) >>> 2;
    wire signed [18:0] cos_r = (x_12 + 19'sd2) >>> 2;
    wire signed [17:0] sin_n = neg_c ? -sin_r : sin_r;
    wire signed [17:0] cos_n = neg_c ? -cos_r : cos_r;
    wire signed [15:0] nco_sin = (sin_n > 32767) ? 16'sd32767 : ((sin_n < -32768) ? -16'sd32768 : sin_n[15:0]);
    wire signed [15:0] nco_cos = (cos_n > 32767) ? 16'sd32767 : ((cos_n < -32768) ? -16'sd32768 : cos_n[15:0]);
    assign sin_o = nco_sin;
    assign cos_o = nco_cos;
endmodule

// FIR/decimator generated from search IR ba692c9a46a10206e701371a313f26bd19615e68d5a50ee88b31f7859187b957
module fir_decimator (
    input  wire clk,
    input  wire rst_n,
    input  wire in_valid,
    output wire in_ready,
    input  wire signed [15:0] x_re,
    input  wire signed [15:0] x_im,
    output reg  signed [15:0] y_re,
    output reg  signed [15:0] y_im,
    output reg out_valid,
    input  wire out_ready
);
    reg [31:0] sample_count;
    assign in_ready = ~out_valid | out_ready;
    wire accept = in_valid & in_ready;
    reg signed [15:0] even_re [0:15];
    reg signed [15:0] even_im [0:15];
    reg signed [15:0] odd_re [0:15];
    reg signed [15:0] odd_im [0:15];
    wire signed [32:0] prod_re_p0_0 = $signed({x_re[15], x_re}) * $signed(16'sd15);
    wire signed [32:0] prod_re_p0_1 = $signed({even_re[0][15], even_re[0]}) * $signed(16'sd25);
    wire signed [32:0] prod_re_p0_2 = $signed({even_re[1][15], even_re[1]}) * $signed(-16'sd89);
    wire signed [32:0] prod_re_p0_3 = $signed({even_re[2][15], even_re[2]}) * $signed(16'sd0);
    wire signed [32:0] prod_re_p0_4 = $signed({even_re[3][15], even_re[3]}) * $signed(16'sd334);
    wire signed [32:0] prod_re_p0_5 = $signed({even_re[4][15], even_re[4]}) * $signed(-16'sd365);
    wire signed [32:0] prod_re_p0_6 = $signed({even_re[5][15], even_re[5]}) * $signed(-16'sd661);
    wire signed [32:0] prod_re_p0_7 = $signed({even_re[6][15], even_re[6]}) * $signed(16'sd2387);
    wire signed [32:0] prod_re_p0_8 = $signed({even_re[7][15], even_re[7]}) * $signed(16'sd4902);
    wire signed [32:0] prod_re_p0_9 = $signed({even_re[8][15], even_re[8]}) * $signed(16'sd2387);
    wire signed [32:0] prod_re_p0_10 = $signed({even_re[9][15], even_re[9]}) * $signed(-16'sd661);
    wire signed [32:0] prod_re_p0_11 = $signed({even_re[10][15], even_re[10]}) * $signed(-16'sd365);
    wire signed [32:0] prod_re_p0_12 = $signed({even_re[11][15], even_re[11]}) * $signed(16'sd334);
    wire signed [32:0] prod_re_p0_13 = $signed({even_re[12][15], even_re[12]}) * $signed(16'sd0);
    wire signed [32:0] prod_re_p0_14 = $signed({even_re[13][15], even_re[13]}) * $signed(-16'sd89);
    wire signed [32:0] prod_re_p0_15 = $signed({even_re[14][15], even_re[14]}) * $signed(16'sd25);
    wire signed [32:0] prod_re_p0_16 = $signed({even_re[15][15], even_re[15]}) * $signed(16'sd15);
    wire signed [38:0] term_re_p0_0 = {{6{prod_re_p0_0[32]}}, prod_re_p0_0};
    wire signed [38:0] term_re_p0_1 = {{6{prod_re_p0_1[32]}}, prod_re_p0_1};
    wire signed [38:0] term_re_p0_2 = {{6{prod_re_p0_2[32]}}, prod_re_p0_2};
    wire signed [38:0] term_re_p0_3 = {{6{prod_re_p0_3[32]}}, prod_re_p0_3};
    wire signed [38:0] term_re_p0_4 = {{6{prod_re_p0_4[32]}}, prod_re_p0_4};
    wire signed [38:0] term_re_p0_5 = {{6{prod_re_p0_5[32]}}, prod_re_p0_5};
    wire signed [38:0] term_re_p0_6 = {{6{prod_re_p0_6[32]}}, prod_re_p0_6};
    wire signed [38:0] term_re_p0_7 = {{6{prod_re_p0_7[32]}}, prod_re_p0_7};
    wire signed [38:0] term_re_p0_8 = {{6{prod_re_p0_8[32]}}, prod_re_p0_8};
    wire signed [38:0] term_re_p0_9 = {{6{prod_re_p0_9[32]}}, prod_re_p0_9};
    wire signed [38:0] term_re_p0_10 = {{6{prod_re_p0_10[32]}}, prod_re_p0_10};
    wire signed [38:0] term_re_p0_11 = {{6{prod_re_p0_11[32]}}, prod_re_p0_11};
    wire signed [38:0] term_re_p0_12 = {{6{prod_re_p0_12[32]}}, prod_re_p0_12};
    wire signed [38:0] term_re_p0_13 = {{6{prod_re_p0_13[32]}}, prod_re_p0_13};
    wire signed [38:0] term_re_p0_14 = {{6{prod_re_p0_14[32]}}, prod_re_p0_14};
    wire signed [38:0] term_re_p0_15 = {{6{prod_re_p0_15[32]}}, prod_re_p0_15};
    wire signed [38:0] term_re_p0_16 = {{6{prod_re_p0_16[32]}}, prod_re_p0_16};
    wire signed [38:0] acc_re_p0 = term_re_p0_0 + term_re_p0_1 + term_re_p0_2 + term_re_p0_3 + term_re_p0_4 + term_re_p0_5 + term_re_p0_6 + term_re_p0_7 + term_re_p0_8 + term_re_p0_9 + term_re_p0_10 + term_re_p0_11 + term_re_p0_12 + term_re_p0_13 + term_re_p0_14 + term_re_p0_15 + term_re_p0_16;
    wire signed [32:0] prod_re_p1_0 = $signed({x_re[15], x_re}) * $signed(16'sd31);
    wire signed [32:0] prod_re_p1_1 = $signed({odd_re[0][15], odd_re[0]}) * $signed(-16'sd19);
    wire signed [32:0] prod_re_p1_2 = $signed({odd_re[1][15], odd_re[1]}) * $signed(-16'sd109);
    wire signed [32:0] prod_re_p1_3 = $signed({odd_re[2][15], odd_re[2]}) * $signed(16'sd211);
    wire signed [32:0] prod_re_p1_4 = $signed({odd_re[3][15], odd_re[3]}) * $signed(16'sd145);
    wire signed [32:0] prod_re_p1_5 = $signed({odd_re[4][15], odd_re[4]}) * $signed(-16'sd828);
    wire signed [32:0] prod_re_p1_6 = $signed({odd_re[5][15], odd_re[5]}) * $signed(16'sd494);
    wire signed [32:0] prod_re_p1_7 = $signed({odd_re[6][15], odd_re[6]}) * $signed(16'sd4171);
    wire signed [32:0] prod_re_p1_8 = $signed({odd_re[7][15], odd_re[7]}) * $signed(16'sd4171);
    wire signed [32:0] prod_re_p1_9 = $signed({odd_re[8][15], odd_re[8]}) * $signed(16'sd494);
    wire signed [32:0] prod_re_p1_10 = $signed({odd_re[9][15], odd_re[9]}) * $signed(-16'sd828);
    wire signed [32:0] prod_re_p1_11 = $signed({odd_re[10][15], odd_re[10]}) * $signed(16'sd145);
    wire signed [32:0] prod_re_p1_12 = $signed({odd_re[11][15], odd_re[11]}) * $signed(16'sd211);
    wire signed [32:0] prod_re_p1_13 = $signed({odd_re[12][15], odd_re[12]}) * $signed(-16'sd109);
    wire signed [32:0] prod_re_p1_14 = $signed({odd_re[13][15], odd_re[13]}) * $signed(-16'sd19);
    wire signed [32:0] prod_re_p1_15 = $signed({odd_re[14][15], odd_re[14]}) * $signed(16'sd31);
    wire signed [38:0] term_re_p1_0 = {{6{prod_re_p1_0[32]}}, prod_re_p1_0};
    wire signed [38:0] term_re_p1_1 = {{6{prod_re_p1_1[32]}}, prod_re_p1_1};
    wire signed [38:0] term_re_p1_2 = {{6{prod_re_p1_2[32]}}, prod_re_p1_2};
    wire signed [38:0] term_re_p1_3 = {{6{prod_re_p1_3[32]}}, prod_re_p1_3};
    wire signed [38:0] term_re_p1_4 = {{6{prod_re_p1_4[32]}}, prod_re_p1_4};
    wire signed [38:0] term_re_p1_5 = {{6{prod_re_p1_5[32]}}, prod_re_p1_5};
    wire signed [38:0] term_re_p1_6 = {{6{prod_re_p1_6[32]}}, prod_re_p1_6};
    wire signed [38:0] term_re_p1_7 = {{6{prod_re_p1_7[32]}}, prod_re_p1_7};
    wire signed [38:0] term_re_p1_8 = {{6{prod_re_p1_8[32]}}, prod_re_p1_8};
    wire signed [38:0] term_re_p1_9 = {{6{prod_re_p1_9[32]}}, prod_re_p1_9};
    wire signed [38:0] term_re_p1_10 = {{6{prod_re_p1_10[32]}}, prod_re_p1_10};
    wire signed [38:0] term_re_p1_11 = {{6{prod_re_p1_11[32]}}, prod_re_p1_11};
    wire signed [38:0] term_re_p1_12 = {{6{prod_re_p1_12[32]}}, prod_re_p1_12};
    wire signed [38:0] term_re_p1_13 = {{6{prod_re_p1_13[32]}}, prod_re_p1_13};
    wire signed [38:0] term_re_p1_14 = {{6{prod_re_p1_14[32]}}, prod_re_p1_14};
    wire signed [38:0] term_re_p1_15 = {{6{prod_re_p1_15[32]}}, prod_re_p1_15};
    wire signed [38:0] acc_re_p1 = term_re_p1_0 + term_re_p1_1 + term_re_p1_2 + term_re_p1_3 + term_re_p1_4 + term_re_p1_5 + term_re_p1_6 + term_re_p1_7 + term_re_p1_8 + term_re_p1_9 + term_re_p1_10 + term_re_p1_11 + term_re_p1_12 + term_re_p1_13 + term_re_p1_14 + term_re_p1_15;
    reg signed [38:0] odd_partial_re;
    wire signed [38:0] acc_poly_re = acc_re_p0 + odd_partial_re;
    wire signed [38:0] accs_poly_re = acc_poly_re;
    wire signed [38:0] shifted_poly_re = (accs_poly_re + 39'sd8192) >>> 14;
    wire signed [15:0] out_poly_re = (shifted_poly_re > 32767) ? 16'sd32767 : ((shifted_poly_re < -32768) ? -16'sd32768 : shifted_poly_re[15:0]);
    wire signed [32:0] prod_im_p0_0 = $signed({x_im[15], x_im}) * $signed(16'sd15);
    wire signed [32:0] prod_im_p0_1 = $signed({even_im[0][15], even_im[0]}) * $signed(16'sd25);
    wire signed [32:0] prod_im_p0_2 = $signed({even_im[1][15], even_im[1]}) * $signed(-16'sd89);
    wire signed [32:0] prod_im_p0_3 = $signed({even_im[2][15], even_im[2]}) * $signed(16'sd0);
    wire signed [32:0] prod_im_p0_4 = $signed({even_im[3][15], even_im[3]}) * $signed(16'sd334);
    wire signed [32:0] prod_im_p0_5 = $signed({even_im[4][15], even_im[4]}) * $signed(-16'sd365);
    wire signed [32:0] prod_im_p0_6 = $signed({even_im[5][15], even_im[5]}) * $signed(-16'sd661);
    wire signed [32:0] prod_im_p0_7 = $signed({even_im[6][15], even_im[6]}) * $signed(16'sd2387);
    wire signed [32:0] prod_im_p0_8 = $signed({even_im[7][15], even_im[7]}) * $signed(16'sd4902);
    wire signed [32:0] prod_im_p0_9 = $signed({even_im[8][15], even_im[8]}) * $signed(16'sd2387);
    wire signed [32:0] prod_im_p0_10 = $signed({even_im[9][15], even_im[9]}) * $signed(-16'sd661);
    wire signed [32:0] prod_im_p0_11 = $signed({even_im[10][15], even_im[10]}) * $signed(-16'sd365);
    wire signed [32:0] prod_im_p0_12 = $signed({even_im[11][15], even_im[11]}) * $signed(16'sd334);
    wire signed [32:0] prod_im_p0_13 = $signed({even_im[12][15], even_im[12]}) * $signed(16'sd0);
    wire signed [32:0] prod_im_p0_14 = $signed({even_im[13][15], even_im[13]}) * $signed(-16'sd89);
    wire signed [32:0] prod_im_p0_15 = $signed({even_im[14][15], even_im[14]}) * $signed(16'sd25);
    wire signed [32:0] prod_im_p0_16 = $signed({even_im[15][15], even_im[15]}) * $signed(16'sd15);
    wire signed [38:0] term_im_p0_0 = {{6{prod_im_p0_0[32]}}, prod_im_p0_0};
    wire signed [38:0] term_im_p0_1 = {{6{prod_im_p0_1[32]}}, prod_im_p0_1};
    wire signed [38:0] term_im_p0_2 = {{6{prod_im_p0_2[32]}}, prod_im_p0_2};
    wire signed [38:0] term_im_p0_3 = {{6{prod_im_p0_3[32]}}, prod_im_p0_3};
    wire signed [38:0] term_im_p0_4 = {{6{prod_im_p0_4[32]}}, prod_im_p0_4};
    wire signed [38:0] term_im_p0_5 = {{6{prod_im_p0_5[32]}}, prod_im_p0_5};
    wire signed [38:0] term_im_p0_6 = {{6{prod_im_p0_6[32]}}, prod_im_p0_6};
    wire signed [38:0] term_im_p0_7 = {{6{prod_im_p0_7[32]}}, prod_im_p0_7};
    wire signed [38:0] term_im_p0_8 = {{6{prod_im_p0_8[32]}}, prod_im_p0_8};
    wire signed [38:0] term_im_p0_9 = {{6{prod_im_p0_9[32]}}, prod_im_p0_9};
    wire signed [38:0] term_im_p0_10 = {{6{prod_im_p0_10[32]}}, prod_im_p0_10};
    wire signed [38:0] term_im_p0_11 = {{6{prod_im_p0_11[32]}}, prod_im_p0_11};
    wire signed [38:0] term_im_p0_12 = {{6{prod_im_p0_12[32]}}, prod_im_p0_12};
    wire signed [38:0] term_im_p0_13 = {{6{prod_im_p0_13[32]}}, prod_im_p0_13};
    wire signed [38:0] term_im_p0_14 = {{6{prod_im_p0_14[32]}}, prod_im_p0_14};
    wire signed [38:0] term_im_p0_15 = {{6{prod_im_p0_15[32]}}, prod_im_p0_15};
    wire signed [38:0] term_im_p0_16 = {{6{prod_im_p0_16[32]}}, prod_im_p0_16};
    wire signed [38:0] acc_im_p0 = term_im_p0_0 + term_im_p0_1 + term_im_p0_2 + term_im_p0_3 + term_im_p0_4 + term_im_p0_5 + term_im_p0_6 + term_im_p0_7 + term_im_p0_8 + term_im_p0_9 + term_im_p0_10 + term_im_p0_11 + term_im_p0_12 + term_im_p0_13 + term_im_p0_14 + term_im_p0_15 + term_im_p0_16;
    wire signed [32:0] prod_im_p1_0 = $signed({x_im[15], x_im}) * $signed(16'sd31);
    wire signed [32:0] prod_im_p1_1 = $signed({odd_im[0][15], odd_im[0]}) * $signed(-16'sd19);
    wire signed [32:0] prod_im_p1_2 = $signed({odd_im[1][15], odd_im[1]}) * $signed(-16'sd109);
    wire signed [32:0] prod_im_p1_3 = $signed({odd_im[2][15], odd_im[2]}) * $signed(16'sd211);
    wire signed [32:0] prod_im_p1_4 = $signed({odd_im[3][15], odd_im[3]}) * $signed(16'sd145);
    wire signed [32:0] prod_im_p1_5 = $signed({odd_im[4][15], odd_im[4]}) * $signed(-16'sd828);
    wire signed [32:0] prod_im_p1_6 = $signed({odd_im[5][15], odd_im[5]}) * $signed(16'sd494);
    wire signed [32:0] prod_im_p1_7 = $signed({odd_im[6][15], odd_im[6]}) * $signed(16'sd4171);
    wire signed [32:0] prod_im_p1_8 = $signed({odd_im[7][15], odd_im[7]}) * $signed(16'sd4171);
    wire signed [32:0] prod_im_p1_9 = $signed({odd_im[8][15], odd_im[8]}) * $signed(16'sd494);
    wire signed [32:0] prod_im_p1_10 = $signed({odd_im[9][15], odd_im[9]}) * $signed(-16'sd828);
    wire signed [32:0] prod_im_p1_11 = $signed({odd_im[10][15], odd_im[10]}) * $signed(16'sd145);
    wire signed [32:0] prod_im_p1_12 = $signed({odd_im[11][15], odd_im[11]}) * $signed(16'sd211);
    wire signed [32:0] prod_im_p1_13 = $signed({odd_im[12][15], odd_im[12]}) * $signed(-16'sd109);
    wire signed [32:0] prod_im_p1_14 = $signed({odd_im[13][15], odd_im[13]}) * $signed(-16'sd19);
    wire signed [32:0] prod_im_p1_15 = $signed({odd_im[14][15], odd_im[14]}) * $signed(16'sd31);
    wire signed [38:0] term_im_p1_0 = {{6{prod_im_p1_0[32]}}, prod_im_p1_0};
    wire signed [38:0] term_im_p1_1 = {{6{prod_im_p1_1[32]}}, prod_im_p1_1};
    wire signed [38:0] term_im_p1_2 = {{6{prod_im_p1_2[32]}}, prod_im_p1_2};
    wire signed [38:0] term_im_p1_3 = {{6{prod_im_p1_3[32]}}, prod_im_p1_3};
    wire signed [38:0] term_im_p1_4 = {{6{prod_im_p1_4[32]}}, prod_im_p1_4};
    wire signed [38:0] term_im_p1_5 = {{6{prod_im_p1_5[32]}}, prod_im_p1_5};
    wire signed [38:0] term_im_p1_6 = {{6{prod_im_p1_6[32]}}, prod_im_p1_6};
    wire signed [38:0] term_im_p1_7 = {{6{prod_im_p1_7[32]}}, prod_im_p1_7};
    wire signed [38:0] term_im_p1_8 = {{6{prod_im_p1_8[32]}}, prod_im_p1_8};
    wire signed [38:0] term_im_p1_9 = {{6{prod_im_p1_9[32]}}, prod_im_p1_9};
    wire signed [38:0] term_im_p1_10 = {{6{prod_im_p1_10[32]}}, prod_im_p1_10};
    wire signed [38:0] term_im_p1_11 = {{6{prod_im_p1_11[32]}}, prod_im_p1_11};
    wire signed [38:0] term_im_p1_12 = {{6{prod_im_p1_12[32]}}, prod_im_p1_12};
    wire signed [38:0] term_im_p1_13 = {{6{prod_im_p1_13[32]}}, prod_im_p1_13};
    wire signed [38:0] term_im_p1_14 = {{6{prod_im_p1_14[32]}}, prod_im_p1_14};
    wire signed [38:0] term_im_p1_15 = {{6{prod_im_p1_15[32]}}, prod_im_p1_15};
    wire signed [38:0] acc_im_p1 = term_im_p1_0 + term_im_p1_1 + term_im_p1_2 + term_im_p1_3 + term_im_p1_4 + term_im_p1_5 + term_im_p1_6 + term_im_p1_7 + term_im_p1_8 + term_im_p1_9 + term_im_p1_10 + term_im_p1_11 + term_im_p1_12 + term_im_p1_13 + term_im_p1_14 + term_im_p1_15;
    reg signed [38:0] odd_partial_im;
    wire signed [38:0] acc_poly_im = acc_im_p0 + odd_partial_im;
    wire signed [38:0] accs_poly_im = acc_poly_im;
    wire signed [38:0] shifted_poly_im = (accs_poly_im + 39'sd8192) >>> 14;
    wire signed [15:0] out_poly_im = (shifted_poly_im > 32767) ? 16'sd32767 : ((shifted_poly_im < -32768) ? -16'sd32768 : shifted_poly_im[15:0]);
    integer phase_index;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (phase_index = 0; phase_index < 16; phase_index = phase_index + 1) begin
                even_re[phase_index] <= 16'sd0;
                even_im[phase_index] <= 16'sd0;
                odd_re[phase_index] <= 16'sd0;
                odd_im[phase_index] <= 16'sd0;
            end
            odd_partial_re <= 39'sd0;
            odd_partial_im <= 39'sd0;
        end else if (accept) begin
            if (sample_count[0] == 1'b0) begin
                even_re[0] <= x_re;
                even_im[0] <= x_im;
                for (phase_index = 1; phase_index < 16; phase_index = phase_index + 1) begin
                    even_re[phase_index] <= even_re[phase_index - 1];
                    even_im[phase_index] <= even_im[phase_index - 1];
                end
            end else begin
                odd_re[0] <= x_re;
                odd_im[0] <= x_im;
                odd_partial_re <= acc_re_p1;
                odd_partial_im <= acc_im_p1;
                for (phase_index = 1; phase_index < 16; phase_index = phase_index + 1) begin
                    odd_re[phase_index] <= odd_re[phase_index - 1];
                    odd_im[phase_index] <= odd_im[phase_index - 1];
                end
            end
        end
    end
    always @(posedge clk) begin
        if (!rst_n) begin
            sample_count <= 32'd0;
            y_re <= 16'sd0;
            y_im <= 16'sd0;
            out_valid <= 1'b0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            if (accept) begin
                if ((sample_count >= 32) && (sample_count[0] == 1'b0)) begin
                    y_re <= out_poly_re;
                    y_im <= out_poly_im;
                    out_valid <= 1'b1;
                end
                sample_count <= sample_count + 32'd1;
            end
        end
    end
endmodule
