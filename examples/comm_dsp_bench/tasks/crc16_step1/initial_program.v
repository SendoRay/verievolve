// 参数化基线：CRC-16 组合逐位展开（16 步，单拍，朴素）
module top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [15:0] data,
    output reg         out_valid,
    input  wire        out_ready,
    output reg  [15:0] crc
);
    // EVOLVE-BLOCK-START
    reg [15:0] acc;
    reg [15:0] c;
    integer k;
    always @(*) begin
        c = acc;
        for (k = 15; k >= 0; k = k - 1) begin
            if ((c[15] ^ data[k]))
                c = (c << 1) ^ 16'h1021;
            else
                c = c << 1;
        end
    end
    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            acc <= 16'd0; out_valid <= 1'b0; crc <= 16'd0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                acc <= c;
                crc <= c;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
