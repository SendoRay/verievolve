// joint_candidate_sha256=ec952dbb73cbd2c8eb9ef1233ba3793d4b7f0dd21c7971e491f488804d666d6e; source_graph_sha256=65ef79d7bbc84002b21a9cc49436a2940a81b1caa113ca09d278112147c701f8
module top(
    input wire clk, input wire rst_n,
    input wire in_valid, output wire in_ready,
    input wire signed [15:0] x,
    output reg out_valid, input wire out_ready,
    output reg signed [39:0] y
);
    reg signed [15:0] delay_1, delay_2, delay_3, delay_4, delay_5, delay_6, delay_7, delay_8, delay_9, delay_10, delay_11, delay_12, delay_13, delay_14, delay_15;
    reg phase;
    reg [4:0] accepted_count;
    wire signed [39:0] x_graph = {{24{x[15]}}, x};
    wire signed [39:0] d1 = {{24{delay_1[15]}}, delay_1};
    wire signed [39:0] d2 = {{24{delay_2[15]}}, delay_2};
    wire signed [39:0] d3 = {{24{delay_3[15]}}, delay_3};
    wire signed [39:0] d4 = {{24{delay_4[15]}}, delay_4};
    wire signed [39:0] d5 = {{24{delay_5[15]}}, delay_5};
    wire signed [39:0] d6 = {{24{delay_6[15]}}, delay_6};
    wire signed [39:0] d7 = {{24{delay_7[15]}}, delay_7};
    wire signed [39:0] d8 = {{24{delay_8[15]}}, delay_8};
    wire signed [39:0] d9 = {{24{delay_9[15]}}, delay_9};
    wire signed [39:0] d10 = {{24{delay_10[15]}}, delay_10};
    wire signed [39:0] d11 = {{24{delay_11[15]}}, delay_11};
    wire signed [39:0] d12 = {{24{delay_12[15]}}, delay_12};
    wire signed [39:0] d13 = {{24{delay_13[15]}}, delay_13};
    wire signed [39:0] d14 = {{24{delay_14[15]}}, delay_14};
    wire signed [39:0] d15 = {{24{delay_15[15]}}, delay_15};
    wire signed [39:0] p0 = $signed(x_graph) * -40'sd79;
    wire signed [39:0] p1 = $signed(d1) * -40'sd136;
    wire signed [39:0] p2 = $signed(d2) * 40'sd312;
    wire signed [39:0] p3 = $signed(d3) * 40'sd654;
    wire signed [39:0] p4 = $signed(d4) * -40'sd1244;
    wire signed [39:0] p5 = $signed(d5) * -40'sd2280;
    wire signed [39:0] p6 = $signed(d6) * 40'sd4501;
    wire signed [39:0] p7 = $signed(d7) * 40'sd14655;
    wire signed [39:0] p8 = $signed(d8) * 40'sd14655;
    wire signed [39:0] p9 = $signed(d9) * 40'sd4501;
    wire signed [39:0] p10 = $signed(d10) * -40'sd2280;
    wire signed [39:0] p11 = $signed(d11) * -40'sd1244;
    wire signed [39:0] p12 = $signed(d12) * 40'sd654;
    wire signed [39:0] p13 = $signed(d13) * 40'sd312;
    wire signed [39:0] p14 = $signed(d14) * -40'sd136;
    wire signed [39:0] p15 = $signed(d15) * -40'sd79;
    wire signed [39:0] s01 = $signed(p0) + $signed(p1);
    wire signed [39:0] s23 = $signed(p2) + $signed(p3);
    wire signed [39:0] s45 = $signed(p4) + $signed(p5);
    wire signed [39:0] s67 = $signed(p6) + $signed(p7);
    wire signed [39:0] s89 = $signed(p8) + $signed(p9);
    wire signed [39:0] s1011 = $signed(p10) + $signed(p11);
    wire signed [39:0] s1213 = $signed(p12) + $signed(p13);
    wire signed [39:0] s1415 = $signed(p14) + $signed(p15);
    wire signed [39:0] s0123 = $signed(s01) + $signed(s23);
    wire signed [39:0] s4567 = $signed(s45) + $signed(s67);
    wire signed [39:0] s891011 = $signed(s89) + $signed(s1011);
    wire signed [39:0] s12131415 = $signed(s1213) + $signed(s1415);
    wire signed [39:0] s01234567 = $signed(s0123) + $signed(s4567);
    wire signed [39:0] s89101112131415 = $signed(s891011) + $signed(s12131415);
    wire signed [39:0] sum = $signed(s01234567) + $signed(s89101112131415);
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            delay_1 <= 16'sd0;
            delay_2 <= 16'sd0;
            delay_3 <= 16'sd0;
            delay_4 <= 16'sd0;
            delay_5 <= 16'sd0;
            delay_6 <= 16'sd0;
            delay_7 <= 16'sd0;
            delay_8 <= 16'sd0;
            delay_9 <= 16'sd0;
            delay_10 <= 16'sd0;
            delay_11 <= 16'sd0;
            delay_12 <= 16'sd0;
            delay_13 <= 16'sd0;
            delay_14 <= 16'sd0;
            delay_15 <= 16'sd0;
            phase <= 1'b0;
            accepted_count <= 5'd0;
            out_valid <= 1'b0;
            y <= 40'sd0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                delay_15 <= delay_14;
                delay_14 <= delay_13;
                delay_13 <= delay_12;
                delay_12 <= delay_11;
                delay_11 <= delay_10;
                delay_10 <= delay_9;
                delay_9 <= delay_8;
                delay_8 <= delay_7;
                delay_7 <= delay_6;
                delay_6 <= delay_5;
                delay_5 <= delay_4;
                delay_4 <= delay_3;
                delay_3 <= delay_2;
                delay_2 <= delay_1;
                delay_1 <= x;
                if (accepted_count != 5'd31)
                    accepted_count <= accepted_count + 1'b1;
                phase <= ~phase;
                if (accepted_count >= 5'd15 && phase == 1'b1) begin
                    y <= sum;
                    out_valid <= 1'b1;
                end
            end
        end
    end
endmodule
