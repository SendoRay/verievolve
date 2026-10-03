// Complete DDC generated from search IR 6aa93731bde13bd210859ed22e80f13ad98e90eec5194cc0fad79f31242067cd
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

// NCO 映射 nco=ir_5b09fd9515cd
module nco_map (
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
    wire [7:0] mi_s;
    wire [6:0] d_s;
    assign ngs_s = z_sin[15];
    assign prs_s = z_sin[14:0];
    wire [15:0] msf_s = 16'd32768 - {1'b0, prs_s};
    assign ms_s = prs_s[14] ? msf_s[14:0] : {1'b0, prs_s[13:0]};
    assign mi_s = ms_s >> 7;
    assign d_s = ms_s[6:0];
    reg signed [15:0] rom_s;
    always @(*) begin
        case (mi_s)
            8'd0: rom_s = 16'sd0;
            8'd1: rom_s = 16'sd402;
            8'd2: rom_s = 16'sd804;
            8'd3: rom_s = 16'sd1206;
            8'd4: rom_s = 16'sd1608;
            8'd5: rom_s = 16'sd2009;
            8'd6: rom_s = 16'sd2411;
            8'd7: rom_s = 16'sd2811;
            8'd8: rom_s = 16'sd3212;
            8'd9: rom_s = 16'sd3612;
            8'd10: rom_s = 16'sd4011;
            8'd11: rom_s = 16'sd4410;
            8'd12: rom_s = 16'sd4808;
            8'd13: rom_s = 16'sd5205;
            8'd14: rom_s = 16'sd5602;
            8'd15: rom_s = 16'sd5998;
            8'd16: rom_s = 16'sd6393;
            8'd17: rom_s = 16'sd6787;
            8'd18: rom_s = 16'sd7180;
            8'd19: rom_s = 16'sd7571;
            8'd20: rom_s = 16'sd7962;
            8'd21: rom_s = 16'sd8351;
            8'd22: rom_s = 16'sd8740;
            8'd23: rom_s = 16'sd9127;
            8'd24: rom_s = 16'sd9512;
            8'd25: rom_s = 16'sd9896;
            8'd26: rom_s = 16'sd10279;
            8'd27: rom_s = 16'sd10660;
            8'd28: rom_s = 16'sd11039;
            8'd29: rom_s = 16'sd11417;
            8'd30: rom_s = 16'sd11793;
            8'd31: rom_s = 16'sd12167;
            8'd32: rom_s = 16'sd12540;
            8'd33: rom_s = 16'sd12910;
            8'd34: rom_s = 16'sd13279;
            8'd35: rom_s = 16'sd13646;
            8'd36: rom_s = 16'sd14010;
            8'd37: rom_s = 16'sd14373;
            8'd38: rom_s = 16'sd14733;
            8'd39: rom_s = 16'sd15091;
            8'd40: rom_s = 16'sd15447;
            8'd41: rom_s = 16'sd15800;
            8'd42: rom_s = 16'sd16151;
            8'd43: rom_s = 16'sd16500;
            8'd44: rom_s = 16'sd16846;
            8'd45: rom_s = 16'sd17190;
            8'd46: rom_s = 16'sd17531;
            8'd47: rom_s = 16'sd17869;
            8'd48: rom_s = 16'sd18205;
            8'd49: rom_s = 16'sd18538;
            8'd50: rom_s = 16'sd18868;
            8'd51: rom_s = 16'sd19195;
            8'd52: rom_s = 16'sd19520;
            8'd53: rom_s = 16'sd19841;
            8'd54: rom_s = 16'sd20160;
            8'd55: rom_s = 16'sd20475;
            8'd56: rom_s = 16'sd20788;
            8'd57: rom_s = 16'sd21097;
            8'd58: rom_s = 16'sd21403;
            8'd59: rom_s = 16'sd21706;
            8'd60: rom_s = 16'sd22006;
            8'd61: rom_s = 16'sd22302;
            8'd62: rom_s = 16'sd22595;
            8'd63: rom_s = 16'sd22884;
            8'd64: rom_s = 16'sd23170;
            8'd65: rom_s = 16'sd23453;
            8'd66: rom_s = 16'sd23732;
            8'd67: rom_s = 16'sd24008;
            8'd68: rom_s = 16'sd24279;
            8'd69: rom_s = 16'sd24548;
            8'd70: rom_s = 16'sd24812;
            8'd71: rom_s = 16'sd25073;
            8'd72: rom_s = 16'sd25330;
            8'd73: rom_s = 16'sd25583;
            8'd74: rom_s = 16'sd25833;
            8'd75: rom_s = 16'sd26078;
            8'd76: rom_s = 16'sd26320;
            8'd77: rom_s = 16'sd26557;
            8'd78: rom_s = 16'sd26791;
            8'd79: rom_s = 16'sd27020;
            8'd80: rom_s = 16'sd27246;
            8'd81: rom_s = 16'sd27467;
            8'd82: rom_s = 16'sd27684;
            8'd83: rom_s = 16'sd27897;
            8'd84: rom_s = 16'sd28106;
            8'd85: rom_s = 16'sd28311;
            8'd86: rom_s = 16'sd28511;
            8'd87: rom_s = 16'sd28707;
            8'd88: rom_s = 16'sd28899;
            8'd89: rom_s = 16'sd29086;
            8'd90: rom_s = 16'sd29269;
            8'd91: rom_s = 16'sd29448;
            8'd92: rom_s = 16'sd29622;
            8'd93: rom_s = 16'sd29792;
            8'd94: rom_s = 16'sd29957;
            8'd95: rom_s = 16'sd30118;
            8'd96: rom_s = 16'sd30274;
            8'd97: rom_s = 16'sd30425;
            8'd98: rom_s = 16'sd30572;
            8'd99: rom_s = 16'sd30715;
            8'd100: rom_s = 16'sd30853;
            8'd101: rom_s = 16'sd30986;
            8'd102: rom_s = 16'sd31114;
            8'd103: rom_s = 16'sd31238;
            8'd104: rom_s = 16'sd31357;
            8'd105: rom_s = 16'sd31471;
            8'd106: rom_s = 16'sd31581;
            8'd107: rom_s = 16'sd31686;
            8'd108: rom_s = 16'sd31786;
            8'd109: rom_s = 16'sd31881;
            8'd110: rom_s = 16'sd31972;
            8'd111: rom_s = 16'sd32058;
            8'd112: rom_s = 16'sd32138;
            8'd113: rom_s = 16'sd32214;
            8'd114: rom_s = 16'sd32286;
            8'd115: rom_s = 16'sd32352;
            8'd116: rom_s = 16'sd32413;
            8'd117: rom_s = 16'sd32470;
            8'd118: rom_s = 16'sd32522;
            8'd119: rom_s = 16'sd32568;
            8'd120: rom_s = 16'sd32610;
            8'd121: rom_s = 16'sd32647;
            8'd122: rom_s = 16'sd32679;
            8'd123: rom_s = 16'sd32706;
            8'd124: rom_s = 16'sd32729;
            8'd125: rom_s = 16'sd32746;
            8'd126: rom_s = 16'sd32758;
            8'd127: rom_s = 16'sd32766;
            8'd128: rom_s = 16'sd32767;
            8'd129: rom_s = 16'sd32766;
            default: rom_s = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_s;
    always @(*) begin
        case (mi_s + 1)
            8'd0: rom1_s = 16'sd0;
            8'd1: rom1_s = 16'sd402;
            8'd2: rom1_s = 16'sd804;
            8'd3: rom1_s = 16'sd1206;
            8'd4: rom1_s = 16'sd1608;
            8'd5: rom1_s = 16'sd2009;
            8'd6: rom1_s = 16'sd2411;
            8'd7: rom1_s = 16'sd2811;
            8'd8: rom1_s = 16'sd3212;
            8'd9: rom1_s = 16'sd3612;
            8'd10: rom1_s = 16'sd4011;
            8'd11: rom1_s = 16'sd4410;
            8'd12: rom1_s = 16'sd4808;
            8'd13: rom1_s = 16'sd5205;
            8'd14: rom1_s = 16'sd5602;
            8'd15: rom1_s = 16'sd5998;
            8'd16: rom1_s = 16'sd6393;
            8'd17: rom1_s = 16'sd6787;
            8'd18: rom1_s = 16'sd7180;
            8'd19: rom1_s = 16'sd7571;
            8'd20: rom1_s = 16'sd7962;
            8'd21: rom1_s = 16'sd8351;
            8'd22: rom1_s = 16'sd8740;
            8'd23: rom1_s = 16'sd9127;
            8'd24: rom1_s = 16'sd9512;
            8'd25: rom1_s = 16'sd9896;
            8'd26: rom1_s = 16'sd10279;
            8'd27: rom1_s = 16'sd10660;
            8'd28: rom1_s = 16'sd11039;
            8'd29: rom1_s = 16'sd11417;
            8'd30: rom1_s = 16'sd11793;
            8'd31: rom1_s = 16'sd12167;
            8'd32: rom1_s = 16'sd12540;
            8'd33: rom1_s = 16'sd12910;
            8'd34: rom1_s = 16'sd13279;
            8'd35: rom1_s = 16'sd13646;
            8'd36: rom1_s = 16'sd14010;
            8'd37: rom1_s = 16'sd14373;
            8'd38: rom1_s = 16'sd14733;
            8'd39: rom1_s = 16'sd15091;
            8'd40: rom1_s = 16'sd15447;
            8'd41: rom1_s = 16'sd15800;
            8'd42: rom1_s = 16'sd16151;
            8'd43: rom1_s = 16'sd16500;
            8'd44: rom1_s = 16'sd16846;
            8'd45: rom1_s = 16'sd17190;
            8'd46: rom1_s = 16'sd17531;
            8'd47: rom1_s = 16'sd17869;
            8'd48: rom1_s = 16'sd18205;
            8'd49: rom1_s = 16'sd18538;
            8'd50: rom1_s = 16'sd18868;
            8'd51: rom1_s = 16'sd19195;
            8'd52: rom1_s = 16'sd19520;
            8'd53: rom1_s = 16'sd19841;
            8'd54: rom1_s = 16'sd20160;
            8'd55: rom1_s = 16'sd20475;
            8'd56: rom1_s = 16'sd20788;
            8'd57: rom1_s = 16'sd21097;
            8'd58: rom1_s = 16'sd21403;
            8'd59: rom1_s = 16'sd21706;
            8'd60: rom1_s = 16'sd22006;
            8'd61: rom1_s = 16'sd22302;
            8'd62: rom1_s = 16'sd22595;
            8'd63: rom1_s = 16'sd22884;
            8'd64: rom1_s = 16'sd23170;
            8'd65: rom1_s = 16'sd23453;
            8'd66: rom1_s = 16'sd23732;
            8'd67: rom1_s = 16'sd24008;
            8'd68: rom1_s = 16'sd24279;
            8'd69: rom1_s = 16'sd24548;
            8'd70: rom1_s = 16'sd24812;
            8'd71: rom1_s = 16'sd25073;
            8'd72: rom1_s = 16'sd25330;
            8'd73: rom1_s = 16'sd25583;
            8'd74: rom1_s = 16'sd25833;
            8'd75: rom1_s = 16'sd26078;
            8'd76: rom1_s = 16'sd26320;
            8'd77: rom1_s = 16'sd26557;
            8'd78: rom1_s = 16'sd26791;
            8'd79: rom1_s = 16'sd27020;
            8'd80: rom1_s = 16'sd27246;
            8'd81: rom1_s = 16'sd27467;
            8'd82: rom1_s = 16'sd27684;
            8'd83: rom1_s = 16'sd27897;
            8'd84: rom1_s = 16'sd28106;
            8'd85: rom1_s = 16'sd28311;
            8'd86: rom1_s = 16'sd28511;
            8'd87: rom1_s = 16'sd28707;
            8'd88: rom1_s = 16'sd28899;
            8'd89: rom1_s = 16'sd29086;
            8'd90: rom1_s = 16'sd29269;
            8'd91: rom1_s = 16'sd29448;
            8'd92: rom1_s = 16'sd29622;
            8'd93: rom1_s = 16'sd29792;
            8'd94: rom1_s = 16'sd29957;
            8'd95: rom1_s = 16'sd30118;
            8'd96: rom1_s = 16'sd30274;
            8'd97: rom1_s = 16'sd30425;
            8'd98: rom1_s = 16'sd30572;
            8'd99: rom1_s = 16'sd30715;
            8'd100: rom1_s = 16'sd30853;
            8'd101: rom1_s = 16'sd30986;
            8'd102: rom1_s = 16'sd31114;
            8'd103: rom1_s = 16'sd31238;
            8'd104: rom1_s = 16'sd31357;
            8'd105: rom1_s = 16'sd31471;
            8'd106: rom1_s = 16'sd31581;
            8'd107: rom1_s = 16'sd31686;
            8'd108: rom1_s = 16'sd31786;
            8'd109: rom1_s = 16'sd31881;
            8'd110: rom1_s = 16'sd31972;
            8'd111: rom1_s = 16'sd32058;
            8'd112: rom1_s = 16'sd32138;
            8'd113: rom1_s = 16'sd32214;
            8'd114: rom1_s = 16'sd32286;
            8'd115: rom1_s = 16'sd32352;
            8'd116: rom1_s = 16'sd32413;
            8'd117: rom1_s = 16'sd32470;
            8'd118: rom1_s = 16'sd32522;
            8'd119: rom1_s = 16'sd32568;
            8'd120: rom1_s = 16'sd32610;
            8'd121: rom1_s = 16'sd32647;
            8'd122: rom1_s = 16'sd32679;
            8'd123: rom1_s = 16'sd32706;
            8'd124: rom1_s = 16'sd32729;
            8'd125: rom1_s = 16'sd32746;
            8'd126: rom1_s = 16'sd32758;
            8'd127: rom1_s = 16'sd32766;
            8'd128: rom1_s = 16'sd32767;
            8'd129: rom1_s = 16'sd32766;
            default: rom1_s = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_s = rom1_s - rom_s;
    wire signed [23:0] lt_s = a1_s * {1'b0, d_s};
    wire signed [17:0] lr_s = {2'b0, rom_s} + (lt_s >>> 7) + {17'd0, (lt_s >>> 6) & 1'b1};
    wire signed [17:0] yw_s = lr_s;
    wire signed [17:0] yn_s = ngs_s ? -yw_s : yw_s;
    wire signed [15:0] out_s = (yn_s > 32767) ? 16'sd32767 : ((yn_s < -32768) ? -16'sd32768 : yn_s[15:0]);
    wire        ngs_c;
    wire [14:0] prs_c;
    wire [14:0] ms_c;
    wire [7:0] mi_c;
    wire [6:0] d_c;
    assign ngs_c = z_cos[15];
    assign prs_c = z_cos[14:0];
    wire [15:0] msf_c = 16'd32768 - {1'b0, prs_c};
    assign ms_c = prs_c[14] ? msf_c[14:0] : {1'b0, prs_c[13:0]};
    assign mi_c = ms_c >> 7;
    assign d_c = ms_c[6:0];
    reg signed [15:0] rom_c;
    always @(*) begin
        case (mi_c)
            8'd0: rom_c = 16'sd0;
            8'd1: rom_c = 16'sd402;
            8'd2: rom_c = 16'sd804;
            8'd3: rom_c = 16'sd1206;
            8'd4: rom_c = 16'sd1608;
            8'd5: rom_c = 16'sd2009;
            8'd6: rom_c = 16'sd2411;
            8'd7: rom_c = 16'sd2811;
            8'd8: rom_c = 16'sd3212;
            8'd9: rom_c = 16'sd3612;
            8'd10: rom_c = 16'sd4011;
            8'd11: rom_c = 16'sd4410;
            8'd12: rom_c = 16'sd4808;
            8'd13: rom_c = 16'sd5205;
            8'd14: rom_c = 16'sd5602;
            8'd15: rom_c = 16'sd5998;
            8'd16: rom_c = 16'sd6393;
            8'd17: rom_c = 16'sd6787;
            8'd18: rom_c = 16'sd7180;
            8'd19: rom_c = 16'sd7571;
            8'd20: rom_c = 16'sd7962;
            8'd21: rom_c = 16'sd8351;
            8'd22: rom_c = 16'sd8740;
            8'd23: rom_c = 16'sd9127;
            8'd24: rom_c = 16'sd9512;
            8'd25: rom_c = 16'sd9896;
            8'd26: rom_c = 16'sd10279;
            8'd27: rom_c = 16'sd10660;
            8'd28: rom_c = 16'sd11039;
            8'd29: rom_c = 16'sd11417;
            8'd30: rom_c = 16'sd11793;
            8'd31: rom_c = 16'sd12167;
            8'd32: rom_c = 16'sd12540;
            8'd33: rom_c = 16'sd12910;
            8'd34: rom_c = 16'sd13279;
            8'd35: rom_c = 16'sd13646;
            8'd36: rom_c = 16'sd14010;
            8'd37: rom_c = 16'sd14373;
            8'd38: rom_c = 16'sd14733;
            8'd39: rom_c = 16'sd15091;
            8'd40: rom_c = 16'sd15447;
            8'd41: rom_c = 16'sd15800;
            8'd42: rom_c = 16'sd16151;
            8'd43: rom_c = 16'sd16500;
            8'd44: rom_c = 16'sd16846;
            8'd45: rom_c = 16'sd17190;
            8'd46: rom_c = 16'sd17531;
            8'd47: rom_c = 16'sd17869;
            8'd48: rom_c = 16'sd18205;
            8'd49: rom_c = 16'sd18538;
            8'd50: rom_c = 16'sd18868;
            8'd51: rom_c = 16'sd19195;
            8'd52: rom_c = 16'sd19520;
            8'd53: rom_c = 16'sd19841;
            8'd54: rom_c = 16'sd20160;
            8'd55: rom_c = 16'sd20475;
            8'd56: rom_c = 16'sd20788;
            8'd57: rom_c = 16'sd21097;
            8'd58: rom_c = 16'sd21403;
            8'd59: rom_c = 16'sd21706;
            8'd60: rom_c = 16'sd22006;
            8'd61: rom_c = 16'sd22302;
            8'd62: rom_c = 16'sd22595;
            8'd63: rom_c = 16'sd22884;
            8'd64: rom_c = 16'sd23170;
            8'd65: rom_c = 16'sd23453;
            8'd66: rom_c = 16'sd23732;
            8'd67: rom_c = 16'sd24008;
            8'd68: rom_c = 16'sd24279;
            8'd69: rom_c = 16'sd24548;
            8'd70: rom_c = 16'sd24812;
            8'd71: rom_c = 16'sd25073;
            8'd72: rom_c = 16'sd25330;
            8'd73: rom_c = 16'sd25583;
            8'd74: rom_c = 16'sd25833;
            8'd75: rom_c = 16'sd26078;
            8'd76: rom_c = 16'sd26320;
            8'd77: rom_c = 16'sd26557;
            8'd78: rom_c = 16'sd26791;
            8'd79: rom_c = 16'sd27020;
            8'd80: rom_c = 16'sd27246;
            8'd81: rom_c = 16'sd27467;
            8'd82: rom_c = 16'sd27684;
            8'd83: rom_c = 16'sd27897;
            8'd84: rom_c = 16'sd28106;
            8'd85: rom_c = 16'sd28311;
            8'd86: rom_c = 16'sd28511;
            8'd87: rom_c = 16'sd28707;
            8'd88: rom_c = 16'sd28899;
            8'd89: rom_c = 16'sd29086;
            8'd90: rom_c = 16'sd29269;
            8'd91: rom_c = 16'sd29448;
            8'd92: rom_c = 16'sd29622;
            8'd93: rom_c = 16'sd29792;
            8'd94: rom_c = 16'sd29957;
            8'd95: rom_c = 16'sd30118;
            8'd96: rom_c = 16'sd30274;
            8'd97: rom_c = 16'sd30425;
            8'd98: rom_c = 16'sd30572;
            8'd99: rom_c = 16'sd30715;
            8'd100: rom_c = 16'sd30853;
            8'd101: rom_c = 16'sd30986;
            8'd102: rom_c = 16'sd31114;
            8'd103: rom_c = 16'sd31238;
            8'd104: rom_c = 16'sd31357;
            8'd105: rom_c = 16'sd31471;
            8'd106: rom_c = 16'sd31581;
            8'd107: rom_c = 16'sd31686;
            8'd108: rom_c = 16'sd31786;
            8'd109: rom_c = 16'sd31881;
            8'd110: rom_c = 16'sd31972;
            8'd111: rom_c = 16'sd32058;
            8'd112: rom_c = 16'sd32138;
            8'd113: rom_c = 16'sd32214;
            8'd114: rom_c = 16'sd32286;
            8'd115: rom_c = 16'sd32352;
            8'd116: rom_c = 16'sd32413;
            8'd117: rom_c = 16'sd32470;
            8'd118: rom_c = 16'sd32522;
            8'd119: rom_c = 16'sd32568;
            8'd120: rom_c = 16'sd32610;
            8'd121: rom_c = 16'sd32647;
            8'd122: rom_c = 16'sd32679;
            8'd123: rom_c = 16'sd32706;
            8'd124: rom_c = 16'sd32729;
            8'd125: rom_c = 16'sd32746;
            8'd126: rom_c = 16'sd32758;
            8'd127: rom_c = 16'sd32766;
            8'd128: rom_c = 16'sd32767;
            8'd129: rom_c = 16'sd32766;
            default: rom_c = 16'sd0;
        endcase
    end
    reg signed [15:0] rom1_c;
    always @(*) begin
        case (mi_c + 1)
            8'd0: rom1_c = 16'sd0;
            8'd1: rom1_c = 16'sd402;
            8'd2: rom1_c = 16'sd804;
            8'd3: rom1_c = 16'sd1206;
            8'd4: rom1_c = 16'sd1608;
            8'd5: rom1_c = 16'sd2009;
            8'd6: rom1_c = 16'sd2411;
            8'd7: rom1_c = 16'sd2811;
            8'd8: rom1_c = 16'sd3212;
            8'd9: rom1_c = 16'sd3612;
            8'd10: rom1_c = 16'sd4011;
            8'd11: rom1_c = 16'sd4410;
            8'd12: rom1_c = 16'sd4808;
            8'd13: rom1_c = 16'sd5205;
            8'd14: rom1_c = 16'sd5602;
            8'd15: rom1_c = 16'sd5998;
            8'd16: rom1_c = 16'sd6393;
            8'd17: rom1_c = 16'sd6787;
            8'd18: rom1_c = 16'sd7180;
            8'd19: rom1_c = 16'sd7571;
            8'd20: rom1_c = 16'sd7962;
            8'd21: rom1_c = 16'sd8351;
            8'd22: rom1_c = 16'sd8740;
            8'd23: rom1_c = 16'sd9127;
            8'd24: rom1_c = 16'sd9512;
            8'd25: rom1_c = 16'sd9896;
            8'd26: rom1_c = 16'sd10279;
            8'd27: rom1_c = 16'sd10660;
            8'd28: rom1_c = 16'sd11039;
            8'd29: rom1_c = 16'sd11417;
            8'd30: rom1_c = 16'sd11793;
            8'd31: rom1_c = 16'sd12167;
            8'd32: rom1_c = 16'sd12540;
            8'd33: rom1_c = 16'sd12910;
            8'd34: rom1_c = 16'sd13279;
            8'd35: rom1_c = 16'sd13646;
            8'd36: rom1_c = 16'sd14010;
            8'd37: rom1_c = 16'sd14373;
            8'd38: rom1_c = 16'sd14733;
            8'd39: rom1_c = 16'sd15091;
            8'd40: rom1_c = 16'sd15447;
            8'd41: rom1_c = 16'sd15800;
            8'd42: rom1_c = 16'sd16151;
            8'd43: rom1_c = 16'sd16500;
            8'd44: rom1_c = 16'sd16846;
            8'd45: rom1_c = 16'sd17190;
            8'd46: rom1_c = 16'sd17531;
            8'd47: rom1_c = 16'sd17869;
            8'd48: rom1_c = 16'sd18205;
            8'd49: rom1_c = 16'sd18538;
            8'd50: rom1_c = 16'sd18868;
            8'd51: rom1_c = 16'sd19195;
            8'd52: rom1_c = 16'sd19520;
            8'd53: rom1_c = 16'sd19841;
            8'd54: rom1_c = 16'sd20160;
            8'd55: rom1_c = 16'sd20475;
            8'd56: rom1_c = 16'sd20788;
            8'd57: rom1_c = 16'sd21097;
            8'd58: rom1_c = 16'sd21403;
            8'd59: rom1_c = 16'sd21706;
            8'd60: rom1_c = 16'sd22006;
            8'd61: rom1_c = 16'sd22302;
            8'd62: rom1_c = 16'sd22595;
            8'd63: rom1_c = 16'sd22884;
            8'd64: rom1_c = 16'sd23170;
            8'd65: rom1_c = 16'sd23453;
            8'd66: rom1_c = 16'sd23732;
            8'd67: rom1_c = 16'sd24008;
            8'd68: rom1_c = 16'sd24279;
            8'd69: rom1_c = 16'sd24548;
            8'd70: rom1_c = 16'sd24812;
            8'd71: rom1_c = 16'sd25073;
            8'd72: rom1_c = 16'sd25330;
            8'd73: rom1_c = 16'sd25583;
            8'd74: rom1_c = 16'sd25833;
            8'd75: rom1_c = 16'sd26078;
            8'd76: rom1_c = 16'sd26320;
            8'd77: rom1_c = 16'sd26557;
            8'd78: rom1_c = 16'sd26791;
            8'd79: rom1_c = 16'sd27020;
            8'd80: rom1_c = 16'sd27246;
            8'd81: rom1_c = 16'sd27467;
            8'd82: rom1_c = 16'sd27684;
            8'd83: rom1_c = 16'sd27897;
            8'd84: rom1_c = 16'sd28106;
            8'd85: rom1_c = 16'sd28311;
            8'd86: rom1_c = 16'sd28511;
            8'd87: rom1_c = 16'sd28707;
            8'd88: rom1_c = 16'sd28899;
            8'd89: rom1_c = 16'sd29086;
            8'd90: rom1_c = 16'sd29269;
            8'd91: rom1_c = 16'sd29448;
            8'd92: rom1_c = 16'sd29622;
            8'd93: rom1_c = 16'sd29792;
            8'd94: rom1_c = 16'sd29957;
            8'd95: rom1_c = 16'sd30118;
            8'd96: rom1_c = 16'sd30274;
            8'd97: rom1_c = 16'sd30425;
            8'd98: rom1_c = 16'sd30572;
            8'd99: rom1_c = 16'sd30715;
            8'd100: rom1_c = 16'sd30853;
            8'd101: rom1_c = 16'sd30986;
            8'd102: rom1_c = 16'sd31114;
            8'd103: rom1_c = 16'sd31238;
            8'd104: rom1_c = 16'sd31357;
            8'd105: rom1_c = 16'sd31471;
            8'd106: rom1_c = 16'sd31581;
            8'd107: rom1_c = 16'sd31686;
            8'd108: rom1_c = 16'sd31786;
            8'd109: rom1_c = 16'sd31881;
            8'd110: rom1_c = 16'sd31972;
            8'd111: rom1_c = 16'sd32058;
            8'd112: rom1_c = 16'sd32138;
            8'd113: rom1_c = 16'sd32214;
            8'd114: rom1_c = 16'sd32286;
            8'd115: rom1_c = 16'sd32352;
            8'd116: rom1_c = 16'sd32413;
            8'd117: rom1_c = 16'sd32470;
            8'd118: rom1_c = 16'sd32522;
            8'd119: rom1_c = 16'sd32568;
            8'd120: rom1_c = 16'sd32610;
            8'd121: rom1_c = 16'sd32647;
            8'd122: rom1_c = 16'sd32679;
            8'd123: rom1_c = 16'sd32706;
            8'd124: rom1_c = 16'sd32729;
            8'd125: rom1_c = 16'sd32746;
            8'd126: rom1_c = 16'sd32758;
            8'd127: rom1_c = 16'sd32766;
            8'd128: rom1_c = 16'sd32767;
            8'd129: rom1_c = 16'sd32766;
            default: rom1_c = 16'sd0;
        endcase
    end
    wire signed [15:0] a1_c = rom1_c - rom_c;
    wire signed [23:0] lt_c = a1_c * {1'b0, d_c};
    wire signed [17:0] lr_c = {2'b0, rom_c} + (lt_c >>> 7) + {17'd0, (lt_c >>> 6) & 1'b1};
    wire signed [17:0] yw_c = lr_c;
    wire signed [17:0] yn_c = ngs_c ? -yw_c : yw_c;
    wire signed [15:0] out_c = (yn_c > 32767) ? 16'sd32767 : ((yn_c < -32768) ? -16'sd32768 : yn_c[15:0]);
    wire signed [15:0] nco_sin = out_s;
    wire signed [15:0] nco_cos = out_c;
    assign sin_o = nco_sin;
    assign cos_o = nco_cos;
endmodule

// FIR/decimator generated from search IR 1229e4a2966b0a4becb7a3da5db164bf50ec6e91a411fa8c88b3882e89e0eaa8
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
    wire signed [32:0] prod_re_1 = $signed(pre_re_1) * $signed(16'sd31);
    wire signed [16:0] pre_re_2 = $signed(line_re[1]) + $signed(line_re[29]);
    wire signed [32:0] prod_re_2 = $signed(pre_re_2) * $signed(16'sd25);
    wire signed [16:0] pre_re_3 = $signed(line_re[2]) + $signed(line_re[28]);
    wire signed [32:0] prod_re_3 = $signed(pre_re_3) * $signed(-16'sd19);
    wire signed [16:0] pre_re_4 = $signed(line_re[3]) + $signed(line_re[27]);
    wire signed [32:0] prod_re_4 = $signed(pre_re_4) * $signed(-16'sd89);
    wire signed [16:0] pre_re_5 = $signed(line_re[4]) + $signed(line_re[26]);
    wire signed [32:0] prod_re_5 = $signed(pre_re_5) * $signed(-16'sd109);
    wire signed [16:0] pre_re_6 = $signed(line_re[5]) + $signed(line_re[25]);
    wire signed [32:0] prod_re_6 = $signed(pre_re_6) * $signed(16'sd0);
    wire signed [16:0] pre_re_7 = $signed(line_re[6]) + $signed(line_re[24]);
    wire signed [32:0] prod_re_7 = $signed(pre_re_7) * $signed(16'sd211);
    wire signed [16:0] pre_re_8 = $signed(line_re[7]) + $signed(line_re[23]);
    wire signed [32:0] prod_re_8 = $signed(pre_re_8) * $signed(16'sd334);
    wire signed [16:0] pre_re_9 = $signed(line_re[8]) + $signed(line_re[22]);
    wire signed [32:0] prod_re_9 = $signed(pre_re_9) * $signed(16'sd145);
    wire signed [16:0] pre_re_10 = $signed(line_re[9]) + $signed(line_re[21]);
    wire signed [32:0] prod_re_10 = $signed(pre_re_10) * $signed(-16'sd365);
    wire signed [16:0] pre_re_11 = $signed(line_re[10]) + $signed(line_re[20]);
    wire signed [32:0] prod_re_11 = $signed(pre_re_11) * $signed(-16'sd828);
    wire signed [16:0] pre_re_12 = $signed(line_re[11]) + $signed(line_re[19]);
    wire signed [32:0] prod_re_12 = $signed(pre_re_12) * $signed(-16'sd661);
    wire signed [16:0] pre_re_13 = $signed(line_re[12]) + $signed(line_re[18]);
    wire signed [32:0] prod_re_13 = $signed(pre_re_13) * $signed(16'sd494);
    wire signed [16:0] pre_re_14 = $signed(line_re[13]) + $signed(line_re[17]);
    wire signed [32:0] prod_re_14 = $signed(pre_re_14) * $signed(16'sd2387);
    wire signed [16:0] pre_re_15 = $signed(line_re[14]) + $signed(line_re[16]);
    wire signed [32:0] prod_re_15 = $signed(pre_re_15) * $signed(16'sd4171);
    wire signed [32:0] prod_re_center = $signed({line_re[15][15], line_re[15]}) * $signed(16'sd4902);
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
    wire signed [38:0] shifted_direct_re = (accs_direct_re + 39'sd8192) >>> 14;
    wire signed [15:0] out_direct_re = (shifted_direct_re > 32767) ? 16'sd32767 : ((shifted_direct_re < -32768) ? -16'sd32768 : shifted_direct_re[15:0]);
    wire signed [16:0] pre_im_0 = $signed(x_im) + $signed(line_im[31]);
    wire signed [32:0] prod_im_0 = $signed(pre_im_0) * $signed(16'sd15);
    wire signed [16:0] pre_im_1 = $signed(line_im[0]) + $signed(line_im[30]);
    wire signed [32:0] prod_im_1 = $signed(pre_im_1) * $signed(16'sd31);
    wire signed [16:0] pre_im_2 = $signed(line_im[1]) + $signed(line_im[29]);
    wire signed [32:0] prod_im_2 = $signed(pre_im_2) * $signed(16'sd25);
    wire signed [16:0] pre_im_3 = $signed(line_im[2]) + $signed(line_im[28]);
    wire signed [32:0] prod_im_3 = $signed(pre_im_3) * $signed(-16'sd19);
    wire signed [16:0] pre_im_4 = $signed(line_im[3]) + $signed(line_im[27]);
    wire signed [32:0] prod_im_4 = $signed(pre_im_4) * $signed(-16'sd89);
    wire signed [16:0] pre_im_5 = $signed(line_im[4]) + $signed(line_im[26]);
    wire signed [32:0] prod_im_5 = $signed(pre_im_5) * $signed(-16'sd109);
    wire signed [16:0] pre_im_6 = $signed(line_im[5]) + $signed(line_im[25]);
    wire signed [32:0] prod_im_6 = $signed(pre_im_6) * $signed(16'sd0);
    wire signed [16:0] pre_im_7 = $signed(line_im[6]) + $signed(line_im[24]);
    wire signed [32:0] prod_im_7 = $signed(pre_im_7) * $signed(16'sd211);
    wire signed [16:0] pre_im_8 = $signed(line_im[7]) + $signed(line_im[23]);
    wire signed [32:0] prod_im_8 = $signed(pre_im_8) * $signed(16'sd334);
    wire signed [16:0] pre_im_9 = $signed(line_im[8]) + $signed(line_im[22]);
    wire signed [32:0] prod_im_9 = $signed(pre_im_9) * $signed(16'sd145);
    wire signed [16:0] pre_im_10 = $signed(line_im[9]) + $signed(line_im[21]);
    wire signed [32:0] prod_im_10 = $signed(pre_im_10) * $signed(-16'sd365);
    wire signed [16:0] pre_im_11 = $signed(line_im[10]) + $signed(line_im[20]);
    wire signed [32:0] prod_im_11 = $signed(pre_im_11) * $signed(-16'sd828);
    wire signed [16:0] pre_im_12 = $signed(line_im[11]) + $signed(line_im[19]);
    wire signed [32:0] prod_im_12 = $signed(pre_im_12) * $signed(-16'sd661);
    wire signed [16:0] pre_im_13 = $signed(line_im[12]) + $signed(line_im[18]);
    wire signed [32:0] prod_im_13 = $signed(pre_im_13) * $signed(16'sd494);
    wire signed [16:0] pre_im_14 = $signed(line_im[13]) + $signed(line_im[17]);
    wire signed [32:0] prod_im_14 = $signed(pre_im_14) * $signed(16'sd2387);
    wire signed [16:0] pre_im_15 = $signed(line_im[14]) + $signed(line_im[16]);
    wire signed [32:0] prod_im_15 = $signed(pre_im_15) * $signed(16'sd4171);
    wire signed [32:0] prod_im_center = $signed({line_im[15][15], line_im[15]}) * $signed(16'sd4902);
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
    wire signed [38:0] shifted_direct_im = (accs_direct_im + 39'sd8192) >>> 14;
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
