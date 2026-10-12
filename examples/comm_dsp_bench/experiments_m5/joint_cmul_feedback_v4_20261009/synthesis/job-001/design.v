// approximate cmul precision implementation 3e9168f9e45f3e2c54e1546b495743218cae9e0dab1e69528da13b850f94c3ad
// source exact graph SHA256 9ccfe39e62cfe05100683308b53812ce46521e5495d3c1cd6f12bf1f358d3aa4
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
