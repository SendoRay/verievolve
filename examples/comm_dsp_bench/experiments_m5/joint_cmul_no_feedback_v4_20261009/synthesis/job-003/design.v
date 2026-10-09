// approximate cmul precision implementation 84ea1547d63cc381e50babc1e2b2b71ddac69aa3ef64f0f3d495dd470aa067c5
// source exact graph SHA256 777e06368c2097ffee97ba1417e89bbaead491ad198c6ee65df627ff71c08a90
module top(
 input wire clk, input wire rst_n, input wire in_valid, output wire in_ready,
 input wire signed [15:0] a, b, c, d,
 output reg out_valid, input wire out_ready,
 output reg signed [32:0] y_re, y_im
);
    wire signed [38:0] raw_joint_body_000 = $signed(a) * $signed(c);
    wire signed [38:0] joint_body_000 = raw_joint_body_000;
    wire signed [38:0] raw_joint_body_001 = $signed(b) * $signed(d);
    wire signed [38:0] joint_body_001 = ($signed(raw_joint_body_001) >>> 4) <<< 4;
    wire signed [38:0] raw_joint_body_002 = $signed(a) * $signed(d);
    wire signed [38:0] joint_body_002 = raw_joint_body_002;
    wire signed [38:0] raw_joint_body_003 = $signed(b) * $signed(c);
    wire signed [38:0] joint_body_003 = ($signed(raw_joint_body_003) >>> 4) <<< 4;
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
