// 照公式直写（与 seeds/naive.py 逐位等价）：
// y[m] = (h * (x·e^{-j2π f_if n}))[m·R]：整周期正余弦查表混频 + 单级长低通 + 抽取 R 倍。
//
// 离线计算（Python）：
// @py B = spec.input_bits; OB = spec.output_bits; R = spec.r_total
// @py cos_t = [min(max(round(math.cos(2*math.pi*k/65536) * 2**18), -2**19), 2**19-1) for k in range(65536)]
// @py sin_t = [min(max(round(math.sin(2*math.pi*k/65536) * 2**18), -2**19), 2**19-1) for k in range(65536)]
// @py fp, fstop = spec.passband, spec.fs_out - spec.passband
// @py ntaps, beta = scipy.signal.kaiserord(100.0, (fstop - fp) / 0.5); ntaps |= 1
// @py h = scipy.signal.firwin(ntaps, 0.5 * (fp + fstop), window=("kaiser", beta), fs=1.0)
// @py fc = 22 - 1 - math.ceil(math.log2(max(abs(h))) + 1e-12)
// @py fc = fc if max(abs(round(c * 2.0**fc)) for c in h) <= 2**21 - 1 else fc - 1
// @py coef = [int(round(c * 2.0**fc)) for c in h]
// @py SW = 22 + 23 + math.ceil(math.log2(ntaps)) + 2
// @hex cos.hex 20 cos_t
// @hex sin.hex 20 sin_t
// @hex coef.hex 23 coef
module top (
    input wire clk, input wire rst, input wire in_valid,
    input wire signed [{{B-1}}:0] in_i,
    output reg out_valid,
    output reg signed [{{OB-1}}:0] out_i, output reg signed [{{OB-1}}:0] out_q
);
    localparam NT = {{ntaps}};
    localparam SW = {{SW}};
    // NCO：32 位相位累加，取高 16 位查整周期表
    reg [31:0] acc;
    always @(posedge clk) if (rst) acc <= 0; else if (in_valid) acc <= acc + 32'd{{spec.fcw}};
    reg signed [19:0] cos_rom [0:65535];
    reg signed [19:0] sin_rom [0:65535];
    initial begin $readmemh("cos.hex", cos_rom); $readmemh("sin.hex", sin_rom); end
    wire signed [19:0] c = cos_rom[acc[31:16]];
    wire signed [19:0] s = sin_rom[acc[31:16]];
    // 混频：乘积 f = (B-1)+18，舍入到 22 位、f=20，饱和
    localparam SH = {{B-1+18-20}};
    wire signed [{{B+20-1}}:0] pi_ = in_i * c;
    wire signed [{{B+20-1}}:0] pq_ = -(in_i * s);
    function signed [21:0] rq22; input signed [{{B+20}}:0] v; reg signed [{{B+20}}:0] t; begin
        t = (v + ({{B+21}}'sd1 <<< (SH-1))) >>> SH;
        rq22 = (t > 2097151) ? 22'h1FFFFF : (t < -2097152) ? 22'h200000 : t[21:0];
    end endfunction
    wire signed [21:0] mi = rq22({pi_[{{B+19}}], pi_});
    wire signed [21:0] mq = rq22({pq_[{{B+19}}], pq_});
    // 单级直接型 FIR（NT 个抽头），对每个输入样点都计算
    reg signed [22:0] coef [0:NT-1];
    initial $readmemh("coef.hex", coef);
    reg signed [21:0] di [0:NT-1];
    reg signed [21:0] dq [0:NT-1];
    integer k, z;
    initial for (z = 0; z < NT; z = z + 1) begin di[z] = 0; dq[z] = 0; end
    // 抽取 R 倍；乘 2^3 后舍入、饱和到输出字长（f = 20+fc-3 → OB-1）
    localparam OS = {{20 + fc - 3 - (OB - 1)}};
    function signed [{{OB-1}}:0] rqo; input signed [SW-1:0] v; reg signed [SW-1:0] t; begin
        t = (v + ({{SW}}'sd1 <<< (OS-1))) >>> OS;
        rqo = (t > {{2**(OB-1)-1}}) ? {{OB}}'h{{'%x' % (2**(OB-1)-1)}} : (t < -{{2**(OB-1)}}) ? {{OB}}'h{{'%x' % 2**(OB-1)}} : t[{{OB-1}}:0];
    end endfunction
    reg signed [SW-1:0] si, sq;
    reg [{{max(1,(R-1).bit_length())-1}}:0] ph;
    always @(posedge clk) begin
        if (rst) begin ph <= 0; out_valid <= 0; end
        else begin
            out_valid <= in_valid && (ph == 0);
            if (in_valid) begin
                // 直接型 FIR：y[n] = Σ_k h[k]·x[n-k]，x[n] 为当前混频输出
                si = mi * coef[0]; sq = mq * coef[0];
                for (k = 1; k < NT; k = k + 1) begin si = si + di[k-1] * coef[k]; sq = sq + dq[k-1] * coef[k]; end
                for (k = NT-1; k > 0; k = k - 1) begin di[k] <= di[k-1]; dq[k] <= dq[k-1]; end
                di[0] <= mi; dq[0] <= mq;
                ph <= (ph == {{R-1}}) ? 0 : ph + 1;
                if (ph == 0) begin out_i <= rqo(si); out_q <= rqo(sq); end
            end
        end
    end
endmodule
