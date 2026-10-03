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
    nco_leaf_6a814616f04a u_coarse (
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

// NCO 映射 nco=ir_6a814616f04a
module nco_leaf_6a814616f04a (
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
    wire signed [18:0] sin_r = (y_11 + 19'sd2) >>> 2;
    wire signed [18:0] cos_r = (x_11 + 19'sd2) >>> 2;
    wire signed [17:0] sin_n = neg_c ? -sin_r : sin_r;
    wire signed [17:0] cos_n = neg_c ? -cos_r : cos_r;
    wire signed [15:0] nco_sin = (sin_n > 32767) ? 16'sd32767 : ((sin_n < -32768) ? -16'sd32768 : sin_n[15:0]);
    wire signed [15:0] nco_cos = (cos_n > 32767) ? 16'sd32767 : ((cos_n < -32768) ? -16'sd32768 : cos_n[15:0]);
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
