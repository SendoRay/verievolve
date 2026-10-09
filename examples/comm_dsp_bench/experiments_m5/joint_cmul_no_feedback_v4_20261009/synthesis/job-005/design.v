// approximate cmul precision implementation bc1f9b96bcb54dfb853b94b55357b616e3f2a3110550d6d65e238f80bedb59c3
// source exact graph SHA256 0a8eab3c4192e441aa80509843e452c6fb86e0bbb9671375ac8d04ad232d9e48
module top(
 input wire clk, input wire rst_n, input wire in_valid, output wire in_ready,
 input wire signed [15:0] a, b, c, d,
 output reg out_valid, input wire out_ready,
 output reg signed [32:0] y_re, y_im
);
    wire signed [38:0] raw_joint_body_000 = $signed(a) * $signed(c);
    wire signed [38:0] joint_body_000 = raw_joint_body_000;
    wire signed [38:0] raw_joint_body_001 = $signed(b) * $signed(d);
    wire signed [39:0] rounded_joint_body_001 = { raw_joint_body_001[38], raw_joint_body_001 } + 40'sd32;
    wire signed [38:0] joint_body_001 = ($signed(rounded_joint_body_001) >>> 6) <<< 6;
    wire signed [38:0] raw_joint_body_002 = $signed(a) * $signed(d);
    wire signed [38:0] joint_body_002 = raw_joint_body_002;
    wire signed [38:0] raw_joint_body_003 = $signed(b) * $signed(c);
    wire signed [39:0] rounded_joint_body_003 = { raw_joint_body_003[38], raw_joint_body_003 } + 40'sd32;
    wire signed [38:0] joint_body_003 = ($signed(rounded_joint_body_003) >>> 6) <<< 6;
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
