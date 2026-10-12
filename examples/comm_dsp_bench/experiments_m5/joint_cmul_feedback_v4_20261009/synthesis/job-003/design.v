// approximate cmul precision implementation 8dc4ad4aa3c938b5a9dcc3f57c8bc003d95116ede922e4796692569fe3a5f153
// source exact graph SHA256 675d7c3becdd1b8056bcc4fb6b082cf28111e38fa8cf9bb4003b23a42c9c8be0
module top(
 input wire clk, input wire rst_n, input wire in_valid, output wire in_ready,
 input wire signed [15:0] a, b, c, d,
 output reg out_valid, input wire out_ready,
 output reg signed [32:0] y_re, y_im
);
    wire signed [38:0] raw_joint_body_000 = $signed(a) * $signed(c);
    wire signed [39:0] rounded_joint_body_000 = { raw_joint_body_000[38], raw_joint_body_000 } + 40'sd8;
    wire signed [38:0] joint_body_000 = ($signed(rounded_joint_body_000) >>> 4) <<< 4;
    wire signed [38:0] raw_joint_body_001 = $signed(b) * $signed(d);
    wire signed [39:0] rounded_joint_body_001 = { raw_joint_body_001[38], raw_joint_body_001 } + 40'sd8;
    wire signed [38:0] joint_body_001 = ($signed(rounded_joint_body_001) >>> 4) <<< 4;
    wire signed [38:0] raw_joint_body_002 = $signed(a) * $signed(d);
    wire signed [39:0] rounded_joint_body_002 = { raw_joint_body_002[38], raw_joint_body_002 } + 40'sd8;
    wire signed [38:0] joint_body_002 = ($signed(rounded_joint_body_002) >>> 4) <<< 4;
    wire signed [38:0] raw_joint_body_003 = $signed(b) * $signed(c);
    wire signed [39:0] rounded_joint_body_003 = { raw_joint_body_003[38], raw_joint_body_003 } + 40'sd8;
    wire signed [38:0] joint_body_003 = ($signed(rounded_joint_body_003) >>> 4) <<< 4;
    wire signed [38:0] joint_body_004 = $signed(joint_body_000) - $signed(joint_body_001);
    wire signed [38:0] joint_body_005 = $signed(joint_body_002) + $signed(joint_body_003);
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
      if (!rst_n) begin out_valid <= 1'b0; y_re <= 33'sd0; y_im <= 33'sd0; end
      else begin
        if (out_valid && out_ready) out_valid <= 1'b0;
        if (in_valid && in_ready) begin
          y_re <= joint_body_004; y_im <= joint_body_005; out_valid <= 1'b1;
        end
      end
    end
endmodule
