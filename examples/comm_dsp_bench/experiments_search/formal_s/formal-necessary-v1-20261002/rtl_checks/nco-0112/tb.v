`timescale 1ns/1ps
module tb;
reg [31:0] acc;
wire signed [15:0] s, c;
reg [31:0] values [0:65535];
integer i, fh;
nco_map dut(.phase_acc(acc), .sin_o(s), .cos_o(c));
initial begin
  $readmemh("phase.hex", values);
  fh = $fopen("outputs.txt", "w");
  for (i=0; i<65536; i=i+1) begin
    acc = values[i]; #1;
    $fwrite(fh, "%0d %0d\n", s, c);
  end
  $fclose(fh); $finish;
end
endmodule
