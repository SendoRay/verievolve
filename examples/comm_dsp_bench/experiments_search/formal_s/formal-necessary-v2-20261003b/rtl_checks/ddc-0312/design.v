// Complete DDC generated from search IR 65f2ec9b7508419f464bc5d2a44a0fed4f8a91a44416d984d463d4033adf3357
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

// NCO 映射 nco=ir_7e411fa352e6
module nco_map (
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

// FIR/decimator generated from search IR 920508b75258c0d5a5c0e2e18fdde2f7244ea96e306a15791bbf43a155dd6812
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
    reg signed [15:0] line_re [0:31];
    reg signed [15:0] line_im [0:31];
    wire signed [16:0] pre_re_0 = $signed(x_re) + $signed(line_re[31]);
    wire signed [31:0] prod_re_0 = $signed(pre_re_0) * $signed(15'sd8);
    wire signed [31:0] prodq_re_0 = ((prod_re_0 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_1 = $signed(line_re[0]) + $signed(line_re[30]);
    wire signed [31:0] prod_re_1 = $signed(pre_re_1) * $signed(15'sd15);
    wire signed [31:0] prodq_re_1 = ((prod_re_1 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_2 = $signed(line_re[1]) + $signed(line_re[29]);
    wire signed [31:0] prod_re_2 = $signed(pre_re_2) * $signed(15'sd13);
    wire signed [31:0] prodq_re_2 = ((prod_re_2 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_3 = $signed(line_re[2]) + $signed(line_re[28]);
    wire signed [31:0] prod_re_3 = $signed(pre_re_3) * $signed(-15'sd10);
    wire signed [31:0] prodq_re_3 = ((prod_re_3 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_4 = $signed(line_re[3]) + $signed(line_re[27]);
    wire signed [31:0] prod_re_4 = $signed(pre_re_4) * $signed(-15'sd44);
    wire signed [31:0] prodq_re_4 = ((prod_re_4 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_5 = $signed(line_re[4]) + $signed(line_re[26]);
    wire signed [31:0] prod_re_5 = $signed(pre_re_5) * $signed(-15'sd54);
    wire signed [31:0] prodq_re_5 = ((prod_re_5 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_6 = $signed(line_re[5]) + $signed(line_re[25]);
    wire signed [31:0] prod_re_6 = $signed(pre_re_6) * $signed(15'sd0);
    wire signed [31:0] prodq_re_6 = ((prod_re_6 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_7 = $signed(line_re[6]) + $signed(line_re[24]);
    wire signed [31:0] prod_re_7 = $signed(pre_re_7) * $signed(15'sd105);
    wire signed [31:0] prodq_re_7 = ((prod_re_7 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_8 = $signed(line_re[7]) + $signed(line_re[23]);
    wire signed [31:0] prod_re_8 = $signed(pre_re_8) * $signed(15'sd167);
    wire signed [31:0] prodq_re_8 = ((prod_re_8 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_9 = $signed(line_re[8]) + $signed(line_re[22]);
    wire signed [31:0] prod_re_9 = $signed(pre_re_9) * $signed(15'sd72);
    wire signed [31:0] prodq_re_9 = ((prod_re_9 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_10 = $signed(line_re[9]) + $signed(line_re[21]);
    wire signed [31:0] prod_re_10 = $signed(pre_re_10) * $signed(-15'sd182);
    wire signed [31:0] prodq_re_10 = ((prod_re_10 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_11 = $signed(line_re[10]) + $signed(line_re[20]);
    wire signed [31:0] prod_re_11 = $signed(pre_re_11) * $signed(-15'sd414);
    wire signed [31:0] prodq_re_11 = ((prod_re_11 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_12 = $signed(line_re[11]) + $signed(line_re[19]);
    wire signed [31:0] prod_re_12 = $signed(pre_re_12) * $signed(-15'sd331);
    wire signed [31:0] prodq_re_12 = ((prod_re_12 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_13 = $signed(line_re[12]) + $signed(line_re[18]);
    wire signed [31:0] prod_re_13 = $signed(pre_re_13) * $signed(15'sd247);
    wire signed [31:0] prodq_re_13 = ((prod_re_13 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_14 = $signed(line_re[13]) + $signed(line_re[17]);
    wire signed [31:0] prod_re_14 = $signed(pre_re_14) * $signed(15'sd1193);
    wire signed [31:0] prodq_re_14 = ((prod_re_14 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_re_15 = $signed(line_re[14]) + $signed(line_re[16]);
    wire signed [31:0] prod_re_15 = $signed(pre_re_15) * $signed(15'sd2085);
    wire signed [31:0] prodq_re_15 = ((prod_re_15 + 32'sd1) >>> 1) <<< 1;
    wire signed [31:0] prod_re_center = $signed({line_re[15][15], line_re[15]}) * $signed(15'sd2451);
    wire signed [31:0] prodq_re_center = ((prod_re_center + 32'sd1) >>> 1) <<< 1;
    wire signed [37:0] term_direct_re_0 = {{6{prodq_re_0[31]}}, prodq_re_0};
    wire signed [37:0] term_direct_re_1 = {{6{prodq_re_1[31]}}, prodq_re_1};
    wire signed [37:0] term_direct_re_2 = {{6{prodq_re_2[31]}}, prodq_re_2};
    wire signed [37:0] term_direct_re_3 = {{6{prodq_re_3[31]}}, prodq_re_3};
    wire signed [37:0] term_direct_re_4 = {{6{prodq_re_4[31]}}, prodq_re_4};
    wire signed [37:0] term_direct_re_5 = {{6{prodq_re_5[31]}}, prodq_re_5};
    wire signed [37:0] term_direct_re_6 = {{6{prodq_re_6[31]}}, prodq_re_6};
    wire signed [37:0] term_direct_re_7 = {{6{prodq_re_7[31]}}, prodq_re_7};
    wire signed [37:0] term_direct_re_8 = {{6{prodq_re_8[31]}}, prodq_re_8};
    wire signed [37:0] term_direct_re_9 = {{6{prodq_re_9[31]}}, prodq_re_9};
    wire signed [37:0] term_direct_re_10 = {{6{prodq_re_10[31]}}, prodq_re_10};
    wire signed [37:0] term_direct_re_11 = {{6{prodq_re_11[31]}}, prodq_re_11};
    wire signed [37:0] term_direct_re_12 = {{6{prodq_re_12[31]}}, prodq_re_12};
    wire signed [37:0] term_direct_re_13 = {{6{prodq_re_13[31]}}, prodq_re_13};
    wire signed [37:0] term_direct_re_14 = {{6{prodq_re_14[31]}}, prodq_re_14};
    wire signed [37:0] term_direct_re_15 = {{6{prodq_re_15[31]}}, prodq_re_15};
    wire signed [37:0] term_direct_re_16 = {{6{prodq_re_center[31]}}, prodq_re_center};
    wire signed [37:0] acc_direct_re = term_direct_re_0 + term_direct_re_1 + term_direct_re_2 + term_direct_re_3 + term_direct_re_4 + term_direct_re_5 + term_direct_re_6 + term_direct_re_7 + term_direct_re_8 + term_direct_re_9 + term_direct_re_10 + term_direct_re_11 + term_direct_re_12 + term_direct_re_13 + term_direct_re_14 + term_direct_re_15 + term_direct_re_16;
    wire signed [37:0] accs_direct_re = acc_direct_re;
    wire signed [37:0] shifted_direct_re = (accs_direct_re + 38'sd4096) >>> 13;
    wire signed [15:0] out_direct_re = (shifted_direct_re > 32767) ? 16'sd32767 : ((shifted_direct_re < -32768) ? -16'sd32768 : shifted_direct_re[15:0]);
    wire signed [16:0] pre_im_0 = $signed(x_im) + $signed(line_im[31]);
    wire signed [31:0] prod_im_0 = $signed(pre_im_0) * $signed(15'sd8);
    wire signed [31:0] prodq_im_0 = ((prod_im_0 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_1 = $signed(line_im[0]) + $signed(line_im[30]);
    wire signed [31:0] prod_im_1 = $signed(pre_im_1) * $signed(15'sd15);
    wire signed [31:0] prodq_im_1 = ((prod_im_1 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_2 = $signed(line_im[1]) + $signed(line_im[29]);
    wire signed [31:0] prod_im_2 = $signed(pre_im_2) * $signed(15'sd13);
    wire signed [31:0] prodq_im_2 = ((prod_im_2 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_3 = $signed(line_im[2]) + $signed(line_im[28]);
    wire signed [31:0] prod_im_3 = $signed(pre_im_3) * $signed(-15'sd10);
    wire signed [31:0] prodq_im_3 = ((prod_im_3 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_4 = $signed(line_im[3]) + $signed(line_im[27]);
    wire signed [31:0] prod_im_4 = $signed(pre_im_4) * $signed(-15'sd44);
    wire signed [31:0] prodq_im_4 = ((prod_im_4 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_5 = $signed(line_im[4]) + $signed(line_im[26]);
    wire signed [31:0] prod_im_5 = $signed(pre_im_5) * $signed(-15'sd54);
    wire signed [31:0] prodq_im_5 = ((prod_im_5 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_6 = $signed(line_im[5]) + $signed(line_im[25]);
    wire signed [31:0] prod_im_6 = $signed(pre_im_6) * $signed(15'sd0);
    wire signed [31:0] prodq_im_6 = ((prod_im_6 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_7 = $signed(line_im[6]) + $signed(line_im[24]);
    wire signed [31:0] prod_im_7 = $signed(pre_im_7) * $signed(15'sd105);
    wire signed [31:0] prodq_im_7 = ((prod_im_7 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_8 = $signed(line_im[7]) + $signed(line_im[23]);
    wire signed [31:0] prod_im_8 = $signed(pre_im_8) * $signed(15'sd167);
    wire signed [31:0] prodq_im_8 = ((prod_im_8 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_9 = $signed(line_im[8]) + $signed(line_im[22]);
    wire signed [31:0] prod_im_9 = $signed(pre_im_9) * $signed(15'sd72);
    wire signed [31:0] prodq_im_9 = ((prod_im_9 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_10 = $signed(line_im[9]) + $signed(line_im[21]);
    wire signed [31:0] prod_im_10 = $signed(pre_im_10) * $signed(-15'sd182);
    wire signed [31:0] prodq_im_10 = ((prod_im_10 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_11 = $signed(line_im[10]) + $signed(line_im[20]);
    wire signed [31:0] prod_im_11 = $signed(pre_im_11) * $signed(-15'sd414);
    wire signed [31:0] prodq_im_11 = ((prod_im_11 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_12 = $signed(line_im[11]) + $signed(line_im[19]);
    wire signed [31:0] prod_im_12 = $signed(pre_im_12) * $signed(-15'sd331);
    wire signed [31:0] prodq_im_12 = ((prod_im_12 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_13 = $signed(line_im[12]) + $signed(line_im[18]);
    wire signed [31:0] prod_im_13 = $signed(pre_im_13) * $signed(15'sd247);
    wire signed [31:0] prodq_im_13 = ((prod_im_13 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_14 = $signed(line_im[13]) + $signed(line_im[17]);
    wire signed [31:0] prod_im_14 = $signed(pre_im_14) * $signed(15'sd1193);
    wire signed [31:0] prodq_im_14 = ((prod_im_14 + 32'sd1) >>> 1) <<< 1;
    wire signed [16:0] pre_im_15 = $signed(line_im[14]) + $signed(line_im[16]);
    wire signed [31:0] prod_im_15 = $signed(pre_im_15) * $signed(15'sd2085);
    wire signed [31:0] prodq_im_15 = ((prod_im_15 + 32'sd1) >>> 1) <<< 1;
    wire signed [31:0] prod_im_center = $signed({line_im[15][15], line_im[15]}) * $signed(15'sd2451);
    wire signed [31:0] prodq_im_center = ((prod_im_center + 32'sd1) >>> 1) <<< 1;
    wire signed [37:0] term_direct_im_0 = {{6{prodq_im_0[31]}}, prodq_im_0};
    wire signed [37:0] term_direct_im_1 = {{6{prodq_im_1[31]}}, prodq_im_1};
    wire signed [37:0] term_direct_im_2 = {{6{prodq_im_2[31]}}, prodq_im_2};
    wire signed [37:0] term_direct_im_3 = {{6{prodq_im_3[31]}}, prodq_im_3};
    wire signed [37:0] term_direct_im_4 = {{6{prodq_im_4[31]}}, prodq_im_4};
    wire signed [37:0] term_direct_im_5 = {{6{prodq_im_5[31]}}, prodq_im_5};
    wire signed [37:0] term_direct_im_6 = {{6{prodq_im_6[31]}}, prodq_im_6};
    wire signed [37:0] term_direct_im_7 = {{6{prodq_im_7[31]}}, prodq_im_7};
    wire signed [37:0] term_direct_im_8 = {{6{prodq_im_8[31]}}, prodq_im_8};
    wire signed [37:0] term_direct_im_9 = {{6{prodq_im_9[31]}}, prodq_im_9};
    wire signed [37:0] term_direct_im_10 = {{6{prodq_im_10[31]}}, prodq_im_10};
    wire signed [37:0] term_direct_im_11 = {{6{prodq_im_11[31]}}, prodq_im_11};
    wire signed [37:0] term_direct_im_12 = {{6{prodq_im_12[31]}}, prodq_im_12};
    wire signed [37:0] term_direct_im_13 = {{6{prodq_im_13[31]}}, prodq_im_13};
    wire signed [37:0] term_direct_im_14 = {{6{prodq_im_14[31]}}, prodq_im_14};
    wire signed [37:0] term_direct_im_15 = {{6{prodq_im_15[31]}}, prodq_im_15};
    wire signed [37:0] term_direct_im_16 = {{6{prodq_im_center[31]}}, prodq_im_center};
    wire signed [37:0] acc_direct_im = term_direct_im_0 + term_direct_im_1 + term_direct_im_2 + term_direct_im_3 + term_direct_im_4 + term_direct_im_5 + term_direct_im_6 + term_direct_im_7 + term_direct_im_8 + term_direct_im_9 + term_direct_im_10 + term_direct_im_11 + term_direct_im_12 + term_direct_im_13 + term_direct_im_14 + term_direct_im_15 + term_direct_im_16;
    wire signed [37:0] accs_direct_im = acc_direct_im;
    wire signed [37:0] shifted_direct_im = (accs_direct_im + 38'sd4096) >>> 13;
    wire signed [15:0] out_direct_im = (shifted_direct_im > 32767) ? 16'sd32767 : ((shifted_direct_im < -32768) ? -16'sd32768 : shifted_direct_im[15:0]);
    integer line_index;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (line_index = 0; line_index < 32; line_index = line_index + 1) begin
                line_re[line_index] <= 16'sd0;
                line_im[line_index] <= 16'sd0;
            end
        end else if (accept) begin
            line_re[0] <= x_re;
            line_im[0] <= x_im;
            for (line_index = 1; line_index < 32; line_index = line_index + 1) begin
                line_re[line_index] <= line_re[line_index - 1];
                line_im[line_index] <= line_im[line_index - 1];
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
                    y_re <= out_direct_re;
                    y_im <= out_direct_im;
                    out_valid <= 1'b1;
                end
                sample_count <= sample_count + 32'd1;
            end
        end
    end
endmodule
