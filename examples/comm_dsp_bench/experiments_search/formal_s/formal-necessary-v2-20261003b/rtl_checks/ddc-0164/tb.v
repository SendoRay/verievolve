`timescale 1ns/1ps
module tb;
reg clk=0; always #5 clk=~clk;
reg rst_n=0, in_valid=0, out_ready=1;
wire in_ready, out_valid;
reg signed [11:0] i_in=0, q_in=0;
wire signed [15:0] y_re, y_im;
reg signed [11:0] iv[0:191], qv[0:191];
reg signed [15:0] re[0:79], im[0:79], held_re, held_im;
integer i, k;
top dut(.clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_ready(in_ready),
 .fcw(32'd837518623),.i_in(i_in),.q_in(q_in),.y_re(y_re),.y_im(y_im),
 .out_valid(out_valid),.out_ready(out_ready));
initial begin
 $readmemh("i.hex",iv); $readmemh("q.hex",qv);
 $readmemh("re.hex",re); $readmemh("im.hex",im);
 repeat(2) @(posedge clk);
 @(negedge clk); rst_n=1; k=0;
 for(i=0;i<192;i=i+1) begin
   if(i==20 || i==70 || i==100) begin
     @(negedge clk); in_valid=0; out_ready=1;
     repeat(2) begin @(posedge clk); #1;
       if(out_valid !== 0) $fatal(1,"unexpected valid during input bubble");
     end
   end
   @(negedge clk); in_valid=1; i_in=iv[i]; q_in=qv[i]; out_ready=1;
   if(i==33 || i==65 || i==99 || i==133 || i==167) begin
     held_re=y_re; held_im=y_im; out_ready=0;
     repeat(3) begin @(posedge clk); #1;
       if(in_ready !== 0 || out_valid !== 1 || y_re !== held_re || y_im !== held_im)
         $fatal(1,"backpressure violated at %0d",i);
     end
     @(negedge clk); out_ready=1;
   end
   @(posedge clk); #1;
   if(i>=32 && (i%2)==0) begin
     if(out_valid !== 1 || $signed(y_re) !== $signed(re[k]) || $signed(y_im) !== $signed(im[k]))
       $fatal(1,"output mismatch input=%0d output=%0d",i,k);
     k=k+1;
   end else if(out_valid !== 0) $fatal(1,"unexpected valid at %0d",i);
 end
 if(k != 80) $fatal(1,"missing output");
 $display("PASS"); $finish;
end
endmodule
