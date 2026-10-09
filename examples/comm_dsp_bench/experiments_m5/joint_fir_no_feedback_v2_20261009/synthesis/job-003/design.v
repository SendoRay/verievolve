// joint_candidate_sha256=2cbd19f30f2ffc066172349e76a11cc17c903cf29d97741d130931d9c931b033; source_graph_sha256=4743d3db77f51b8b5e41a3547c2a884ad214b14f1072953f9f863de1bc1d5ea0
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
    wire signed [39:0] h0 = $signed(x_graph) + $signed(d15);
    wire signed [39:0] h1 = $signed(d1) + $signed(d14);
    wire signed [39:0] h2 = $signed(d2) + $signed(d13);
    wire signed [39:0] h3 = $signed(d3) + $signed(d12);
    wire signed [39:0] h4 = $signed(d4) + $signed(d11);
    wire signed [39:0] h5 = $signed(d5) + $signed(d10);
    wire signed [39:0] h6 = $signed(d6) + $signed(d9);
    wire signed [39:0] h7 = $signed(d7) + $signed(d8);
    wire signed [39:0] p0 = $signed(h0) * -40'sd79;
    wire signed [39:0] p1 = $signed(h1) * -40'sd136;
    wire signed [39:0] p2 = $signed(h2) * 40'sd312;
    wire signed [39:0] p3 = $signed(h3) * 40'sd654;
    wire signed [39:0] p4 = $signed(h4) * -40'sd1244;
    wire signed [39:0] p5 = $signed(h5) * -40'sd2280;
    wire signed [39:0] p6 = $signed(h6) * 40'sd4501;
    wire signed [39:0] p7 = $signed(h7) * 40'sd14655;
    wire signed [39:0] s0 = $signed(p0) + $signed(p1);
    wire signed [39:0] s1 = $signed(p2) + $signed(p3);
    wire signed [39:0] s2 = $signed(p4) + $signed(p5);
    wire signed [39:0] s3 = $signed(p6) + $signed(p7);
    wire signed [39:0] s4 = $signed(s0) + $signed(s1);
    wire signed [39:0] s5 = $signed(s2) + $signed(s3);
    wire signed [39:0] acc = $signed(s4) + $signed(s5);
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
                    y <= acc;
                    out_valid <= 1'b1;
                end
            end
        end
    end
endmodule
