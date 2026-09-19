// certfit 参数化复数乘法器 so=4 sd=2 mode=rne structure=direct
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] a,
    input  wire signed [15:0] b,
    input  wire signed [15:0] c,
    input  wire signed [15:0] d,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [32:0] y_re,
    output reg  signed [32:0] y_im
);
    // EVOLVE-BLOCK-START

    wire signed [16:0] a_e = a + 17'sd8;
    wire signed [16:0] b_e = b + 17'sd8;
    wire signed [16:0] c_e = c + 17'sd8;
    wire signed [16:0] d_e = d + 17'sd8;
    wire signed [12:0] a_h = a_e >>> 4;
    wire signed [12:0] b_h = b_e >>> 4;
    wire signed [12:0] c_h = c_e >>> 4;
    wire signed [12:0] d_h = d_e >>> 4;

    wire signed [25:0] pac = $signed(a_h) * $signed(c_h);
    wire signed [25:0] pbd = $signed(b_h) * $signed(d_h);
    wire signed [25:0] pad = $signed(a_h) * $signed(d_h);
    wire signed [25:0] pbc = $signed(b_h) * $signed(c_h);

    wire signed [34:0] pac_x = pac;
    wire signed [34:0] pbd_x = pbd;
    wire signed [34:0] pad_x = pad;
    wire signed [34:0] pbc_x = pbc;
    wire signed [34:0] re_pre = (pac_x - pbd_x) <<< 8;
    wire signed [34:0] im_pre = (pad_x + pbc_x) <<< 8;

    wire signed [35:0] re_e = re_pre + 36'sd2;
    wire signed [35:0] im_e = im_pre + 36'sd2;
    wire signed [34:0] re_q = (re_e >>> 2) <<< 2;
    wire signed [34:0] im_q = (im_e >>> 2) <<< 2;
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; y_re <= 0; y_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                y_re <= re_q[32:0]; y_im <= im_q[32:0];
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
