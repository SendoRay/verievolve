// Complete DDC generated from search IR 8c2ef2029befaf860e491032f0ba6af78f57142d8e5054fcc459f56cba7f14ba
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

// NCO 映射 nco=ir_41c9f8db4836
module nco_map (
    input  wire [31:0] phase_acc,
    output wire signed [15:0] sin_o,
    output wire signed [15:0] cos_o
);
    wire [9:0] phase_w = phase_acc[31:22];
    wire [15:0] z_sin = {phase_w, {6{1'b0}}};
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

// FIR/decimator generated from search IR fa752e25019d01305313c640dbc6f3324a180c937e649e7db8c48208b857268c
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
    wire signed [32:0] prod_re_0 = $signed(pre_re_0) * $signed(16'sd15);
    wire signed [16:0] pre_re_1 = $signed(line_re[0]) + $signed(line_re[30]);
    wire signed [32:0] prod_re_1 = $signed(pre_re_1) * $signed(16'sd30);
    wire signed [16:0] pre_re_2 = $signed(line_re[1]) + $signed(line_re[29]);
    wire signed [32:0] prod_re_2 = $signed(pre_re_2) * $signed(16'sd25);
    wire signed [16:0] pre_re_3 = $signed(line_re[2]) + $signed(line_re[28]);
    wire signed [32:0] prod_re_3 = $signed(pre_re_3) * $signed(-16'sd20);
    wire signed [16:0] pre_re_4 = $signed(line_re[3]) + $signed(line_re[27]);
    wire signed [32:0] prod_re_4 = $signed(pre_re_4) * $signed(-16'sd89);
    wire signed [16:0] pre_re_5 = $signed(line_re[4]) + $signed(line_re[26]);
    wire signed [32:0] prod_re_5 = $signed(pre_re_5) * $signed(-16'sd109);
    wire signed [16:0] pre_re_6 = $signed(line_re[5]) + $signed(line_re[25]);
    wire signed [32:0] prod_re_6 = $signed(pre_re_6) * $signed(-16'sd1);
    wire signed [16:0] pre_re_7 = $signed(line_re[6]) + $signed(line_re[24]);
    wire signed [32:0] prod_re_7 = $signed(pre_re_7) * $signed(16'sd210);
    wire signed [16:0] pre_re_8 = $signed(line_re[7]) + $signed(line_re[23]);
    wire signed [32:0] prod_re_8 = $signed(pre_re_8) * $signed(16'sd333);
    wire signed [16:0] pre_re_9 = $signed(line_re[8]) + $signed(line_re[22]);
    wire signed [32:0] prod_re_9 = $signed(pre_re_9) * $signed(16'sd144);
    wire signed [16:0] pre_re_10 = $signed(line_re[9]) + $signed(line_re[21]);
    wire signed [32:0] prod_re_10 = $signed(pre_re_10) * $signed(-16'sd365);
    wire signed [16:0] pre_re_11 = $signed(line_re[10]) + $signed(line_re[20]);
    wire signed [32:0] prod_re_11 = $signed(pre_re_11) * $signed(-16'sd828);
    wire signed [16:0] pre_re_12 = $signed(line_re[11]) + $signed(line_re[19]);
    wire signed [32:0] prod_re_12 = $signed(pre_re_12) * $signed(-16'sd662);
    wire signed [16:0] pre_re_13 = $signed(line_re[12]) + $signed(line_re[18]);
    wire signed [32:0] prod_re_13 = $signed(pre_re_13) * $signed(16'sd494);
    wire signed [16:0] pre_re_14 = $signed(line_re[13]) + $signed(line_re[17]);
    wire signed [32:0] prod_re_14 = $signed(pre_re_14) * $signed(16'sd2386);
    wire signed [16:0] pre_re_15 = $signed(line_re[14]) + $signed(line_re[16]);
    wire signed [32:0] prod_re_15 = $signed(pre_re_15) * $signed(16'sd4170);
    wire signed [32:0] prod_re_center = $signed({line_re[15][15], line_re[15]}) * $signed(16'sd4901);
    wire signed [38:0] term_direct_re_0 = {{6{prod_re_0[32]}}, prod_re_0};
    wire signed [38:0] term_direct_re_1 = {{6{prod_re_1[32]}}, prod_re_1};
    wire signed [38:0] term_direct_re_2 = {{6{prod_re_2[32]}}, prod_re_2};
    wire signed [38:0] term_direct_re_3 = {{6{prod_re_3[32]}}, prod_re_3};
    wire signed [38:0] term_direct_re_4 = {{6{prod_re_4[32]}}, prod_re_4};
    wire signed [38:0] term_direct_re_5 = {{6{prod_re_5[32]}}, prod_re_5};
    wire signed [38:0] term_direct_re_6 = {{6{prod_re_6[32]}}, prod_re_6};
    wire signed [38:0] term_direct_re_7 = {{6{prod_re_7[32]}}, prod_re_7};
    wire signed [38:0] term_direct_re_8 = {{6{prod_re_8[32]}}, prod_re_8};
    wire signed [38:0] term_direct_re_9 = {{6{prod_re_9[32]}}, prod_re_9};
    wire signed [38:0] term_direct_re_10 = {{6{prod_re_10[32]}}, prod_re_10};
    wire signed [38:0] term_direct_re_11 = {{6{prod_re_11[32]}}, prod_re_11};
    wire signed [38:0] term_direct_re_12 = {{6{prod_re_12[32]}}, prod_re_12};
    wire signed [38:0] term_direct_re_13 = {{6{prod_re_13[32]}}, prod_re_13};
    wire signed [38:0] term_direct_re_14 = {{6{prod_re_14[32]}}, prod_re_14};
    wire signed [38:0] term_direct_re_15 = {{6{prod_re_15[32]}}, prod_re_15};
    wire signed [38:0] term_direct_re_16 = {{6{prod_re_center[32]}}, prod_re_center};
    wire signed [38:0] acc_direct_re = term_direct_re_0 + term_direct_re_1 + term_direct_re_2 + term_direct_re_3 + term_direct_re_4 + term_direct_re_5 + term_direct_re_6 + term_direct_re_7 + term_direct_re_8 + term_direct_re_9 + term_direct_re_10 + term_direct_re_11 + term_direct_re_12 + term_direct_re_13 + term_direct_re_14 + term_direct_re_15 + term_direct_re_16;
    wire signed [38:0] accs_direct_re = acc_direct_re;
    wire signed [38:0] shifted_direct_re = (accs_direct_re + 39'sd0) >>> 14;
    wire signed [15:0] out_direct_re = (shifted_direct_re > 32767) ? 16'sd32767 : ((shifted_direct_re < -32768) ? -16'sd32768 : shifted_direct_re[15:0]);
    wire signed [16:0] pre_im_0 = $signed(x_im) + $signed(line_im[31]);
    wire signed [32:0] prod_im_0 = $signed(pre_im_0) * $signed(16'sd15);
    wire signed [16:0] pre_im_1 = $signed(line_im[0]) + $signed(line_im[30]);
    wire signed [32:0] prod_im_1 = $signed(pre_im_1) * $signed(16'sd30);
    wire signed [16:0] pre_im_2 = $signed(line_im[1]) + $signed(line_im[29]);
    wire signed [32:0] prod_im_2 = $signed(pre_im_2) * $signed(16'sd25);
    wire signed [16:0] pre_im_3 = $signed(line_im[2]) + $signed(line_im[28]);
    wire signed [32:0] prod_im_3 = $signed(pre_im_3) * $signed(-16'sd20);
    wire signed [16:0] pre_im_4 = $signed(line_im[3]) + $signed(line_im[27]);
    wire signed [32:0] prod_im_4 = $signed(pre_im_4) * $signed(-16'sd89);
    wire signed [16:0] pre_im_5 = $signed(line_im[4]) + $signed(line_im[26]);
    wire signed [32:0] prod_im_5 = $signed(pre_im_5) * $signed(-16'sd109);
    wire signed [16:0] pre_im_6 = $signed(line_im[5]) + $signed(line_im[25]);
    wire signed [32:0] prod_im_6 = $signed(pre_im_6) * $signed(-16'sd1);
    wire signed [16:0] pre_im_7 = $signed(line_im[6]) + $signed(line_im[24]);
    wire signed [32:0] prod_im_7 = $signed(pre_im_7) * $signed(16'sd210);
    wire signed [16:0] pre_im_8 = $signed(line_im[7]) + $signed(line_im[23]);
    wire signed [32:0] prod_im_8 = $signed(pre_im_8) * $signed(16'sd333);
    wire signed [16:0] pre_im_9 = $signed(line_im[8]) + $signed(line_im[22]);
    wire signed [32:0] prod_im_9 = $signed(pre_im_9) * $signed(16'sd144);
    wire signed [16:0] pre_im_10 = $signed(line_im[9]) + $signed(line_im[21]);
    wire signed [32:0] prod_im_10 = $signed(pre_im_10) * $signed(-16'sd365);
    wire signed [16:0] pre_im_11 = $signed(line_im[10]) + $signed(line_im[20]);
    wire signed [32:0] prod_im_11 = $signed(pre_im_11) * $signed(-16'sd828);
    wire signed [16:0] pre_im_12 = $signed(line_im[11]) + $signed(line_im[19]);
    wire signed [32:0] prod_im_12 = $signed(pre_im_12) * $signed(-16'sd662);
    wire signed [16:0] pre_im_13 = $signed(line_im[12]) + $signed(line_im[18]);
    wire signed [32:0] prod_im_13 = $signed(pre_im_13) * $signed(16'sd494);
    wire signed [16:0] pre_im_14 = $signed(line_im[13]) + $signed(line_im[17]);
    wire signed [32:0] prod_im_14 = $signed(pre_im_14) * $signed(16'sd2386);
    wire signed [16:0] pre_im_15 = $signed(line_im[14]) + $signed(line_im[16]);
    wire signed [32:0] prod_im_15 = $signed(pre_im_15) * $signed(16'sd4170);
    wire signed [32:0] prod_im_center = $signed({line_im[15][15], line_im[15]}) * $signed(16'sd4901);
    wire signed [38:0] term_direct_im_0 = {{6{prod_im_0[32]}}, prod_im_0};
    wire signed [38:0] term_direct_im_1 = {{6{prod_im_1[32]}}, prod_im_1};
    wire signed [38:0] term_direct_im_2 = {{6{prod_im_2[32]}}, prod_im_2};
    wire signed [38:0] term_direct_im_3 = {{6{prod_im_3[32]}}, prod_im_3};
    wire signed [38:0] term_direct_im_4 = {{6{prod_im_4[32]}}, prod_im_4};
    wire signed [38:0] term_direct_im_5 = {{6{prod_im_5[32]}}, prod_im_5};
    wire signed [38:0] term_direct_im_6 = {{6{prod_im_6[32]}}, prod_im_6};
    wire signed [38:0] term_direct_im_7 = {{6{prod_im_7[32]}}, prod_im_7};
    wire signed [38:0] term_direct_im_8 = {{6{prod_im_8[32]}}, prod_im_8};
    wire signed [38:0] term_direct_im_9 = {{6{prod_im_9[32]}}, prod_im_9};
    wire signed [38:0] term_direct_im_10 = {{6{prod_im_10[32]}}, prod_im_10};
    wire signed [38:0] term_direct_im_11 = {{6{prod_im_11[32]}}, prod_im_11};
    wire signed [38:0] term_direct_im_12 = {{6{prod_im_12[32]}}, prod_im_12};
    wire signed [38:0] term_direct_im_13 = {{6{prod_im_13[32]}}, prod_im_13};
    wire signed [38:0] term_direct_im_14 = {{6{prod_im_14[32]}}, prod_im_14};
    wire signed [38:0] term_direct_im_15 = {{6{prod_im_15[32]}}, prod_im_15};
    wire signed [38:0] term_direct_im_16 = {{6{prod_im_center[32]}}, prod_im_center};
    wire signed [38:0] acc_direct_im = term_direct_im_0 + term_direct_im_1 + term_direct_im_2 + term_direct_im_3 + term_direct_im_4 + term_direct_im_5 + term_direct_im_6 + term_direct_im_7 + term_direct_im_8 + term_direct_im_9 + term_direct_im_10 + term_direct_im_11 + term_direct_im_12 + term_direct_im_13 + term_direct_im_14 + term_direct_im_15 + term_direct_im_16;
    wire signed [38:0] accs_direct_im = acc_direct_im;
    wire signed [38:0] shifted_direct_im = (accs_direct_im + 39'sd0) >>> 14;
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
