// approximate cmul precision implementation 643e79cf274ca227cf0588f0bf41c1a52fa05e9a5150bbea1938507d80a75723
// source exact graph SHA256 675d7c3becdd1b8056bcc4fb6b082cf28111e38fa8cf9bb4003b23a42c9c8be0
module top(
 input wire clk, input wire rst_n, input wire in_valid, output wire in_ready,
 input wire signed [15:0] a, b, c, d,
 output reg out_valid, input wire out_ready,
 output reg signed [32:0] y_re, y_im
);
    wire signed [38:0] raw_joint_body_000 = $signed(a) * $signed(c);
    wire signed [38:0] joint_body_000 = raw_joint_body_000;
    wire signed [38:0] raw_joint_body_001 = $signed(b) * $signed(d);
    wire signed [38:0] joint_body_001 = raw_joint_body_001;
    wire signed [38:0] raw_joint_body_002 = $signed(a) * $signed(d);
    wire signed [38:0] joint_body_002 = raw_joint_body_002;
    wire signed [38:0] raw_joint_body_003 = $signed(b) * $signed(c);
    wire signed [38:0] joint_body_003 = raw_joint_body_003;
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
