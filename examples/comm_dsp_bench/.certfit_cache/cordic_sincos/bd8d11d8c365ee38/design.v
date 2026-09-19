// 参数化设计：CORDIC-20（旋转模式，多周期，零乘法器）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] z,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] sin_out,
    output reg  signed [15:0] cos_out
);

    // EVOLVE-BLOCK-START
    reg signed [18:0] x, y;
    reg signed [17:0] za;
    reg [4:0] iter;
    reg        busy, negf;

    wire signed [17:0] z2 = {z[15], z, 1'b0};
    wire fold_hi = (z > 16'sd16384);
    wire fold_lo = (z < -16'sd16384);
    wire signed [17:0] z_fold = fold_hi ? (z2 - 18'sd65536) :
                                 fold_lo ? (z2 + 18'sd65536) : z2;
    wire neg = fold_hi | fold_lo;

    function signed [17:0] alpha_rom;
        input [4:0] i;
        begin
            case (i)
                19'd0: alpha_rom = 18'sd16384;
                19'd1: alpha_rom = 18'sd9672;
                19'd2: alpha_rom = 18'sd5110;
                19'd3: alpha_rom = 18'sd2594;
                19'd4: alpha_rom = 18'sd1302;
                19'd5: alpha_rom = 18'sd652;
                19'd6: alpha_rom = 18'sd326;
                19'd7: alpha_rom = 18'sd163;
                19'd8: alpha_rom = 18'sd81;
                19'd9: alpha_rom = 18'sd41;
                19'd10: alpha_rom = 18'sd20;
                19'd11: alpha_rom = 18'sd10;
                19'd12: alpha_rom = 18'sd5;
                19'd13: alpha_rom = 18'sd3;
                19'd14: alpha_rom = 18'sd1;
                19'd15: alpha_rom = 18'sd1;
                19'd16: alpha_rom = 18'sd0;
                19'd17: alpha_rom = 18'sd0;
                19'd18: alpha_rom = 18'sd0;
                19'd19: alpha_rom = 18'sd0;
                default: alpha_rom = 18'sd0;
            endcase
        end
    endfunction

    wire signed [18:0] xs = x, ys = y;
    wire signed [18:0] xsh = xs >>> iter;
    wire signed [18:0] ysh = ys >>> iter;
    wire zpos = (za >= 0);
    wire signed [17:0] alpha = alpha_rom(iter);

    wire signed [19:0] sin_r = (ys + 20'sd2) >>> 2;
    wire signed [19:0] cos_r = (xs + 20'sd2) >>> 2;
    wire signed [19:0] sin_a = negf ? -sin_r : sin_r;
    wire signed [19:0] cos_a = negf ? -cos_r : cos_r;
    wire signed [15:0] sin_p = (sin_a > 20'sd32767) ? 16'sd32767 :
                               (sin_a < -20'sd32768) ? -16'sd32768 : sin_a[15:0];
    wire signed [15:0] cos_p = (cos_a > 20'sd32767) ? 16'sd32767 :
                               (cos_a < -20'sd32768) ? -16'sd32768 : cos_a[15:0];

    assign in_ready = !busy && (!out_valid || out_ready);

    always @(posedge clk) begin
        if (!rst_n) begin
            x <= 19'sd0; y <= 19'sd0; za <= 18'sd0;
            iter <= 5'd0; busy <= 1'b0; negf <= 1'b0;
            out_valid <= 1'b0; sin_out <= 16'sd0; cos_out <= 16'sd0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            if (busy) begin
                if (iter < 5'd20) begin
                    if (zpos) begin
                        x <= xs - ysh;
                        y <= ys + xsh;
                        za <= za - alpha;
                    end else begin
                        x <= xs + ysh;
                        y <= ys - xsh;
                        za <= za + alpha;
                    end
                    iter <= iter + 5'd1;
                end else begin
                    sin_out   <= sin_p;
                    cos_out   <= cos_p;
                    out_valid <= 1'b1;
                    busy      <= 1'b0;
                end
            end else if (in_valid && in_ready) begin
                x    <= 19'sd79594;
                y    <= 19'sd0;
                za   <= z_fold;
                negf <= neg;
                iter <= 5'd0;
                busy <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
