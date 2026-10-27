// LE 1M RX stage 3: 8-sample symbol integrator (model: integrate),
// s[n] = f[n-7] + ... + f[n], exact in signed 19 bits, zero history at reset.
module le1m_rx_integ #(
    parameter SIDE_W = 9
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                in_valid,
    input  wire signed [15:0]  in_f,
    input  wire [SIDE_W-1:0]   in_side,
    output reg                 out_valid,
    output reg  signed [18:0]  out_s,
    output reg  [SIDE_W-1:0]   out_side
);
    reg signed [15:0] fh [0:7];   // fh[0] = f[n-1] ... fh[7] = f[n-8]
    reg signed [18:0] sum;
    wire signed [18:0] f_in   = {{3{in_f[15]}}, in_f};
    wire signed [18:0] f_old  = {{3{fh[7][15]}}, fh[7]};
    wire signed [18:0] sum_next = sum + f_in - f_old;
    integer k;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            sum <= 19'sd0;
            for (k = 0; k < 8; k = k + 1) fh[k] <= 16'sd0;
        end else if (in_valid) begin
            sum       <= sum_next;
            out_s     <= sum_next;
            out_valid <= 1'b1;
            out_side  <= in_side;
            fh[0]     <= in_f;
            for (k = 1; k < 8; k = k + 1) fh[k] <= fh[k-1];
        end
    end
endmodule
