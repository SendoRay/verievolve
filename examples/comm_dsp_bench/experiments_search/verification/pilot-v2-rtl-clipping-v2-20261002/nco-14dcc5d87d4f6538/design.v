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
    nco_leaf_36e8c6ce47a8 u_coarse (
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

// NCO 映射 nco=ir_36e8c6ce47a8
module nco_leaf_36e8c6ce47a8 (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [11:0] phase_w = phase_acc[31:20];
    wire [15:0] z_sin = {phase_w, {4{1'b0}}};
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
