// RX moving-sum integrator shared by the LE 1M and 802.15.4 receivers
// (model: le1m_rx.integrate, at N=8 and N=4): a sliding window of
// the last N 16-bit samples, s[n] = f[n-(N-1)] + ... + f[n], exact in signed
// (16 + $clog2(N)) bits, zero history at reset. The sideband (the RSSI
// magnitude) rides along unchanged. le1m_rx instantiates N=8, oqpsk_rx N=4.
module rx_moving_sum #(
    parameter N      = 8,
    parameter SIDE_W = 9,
    parameter OUT_W  = 16 + $clog2(N)
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    in_valid,
    input  wire signed [15:0]      in_f,
    input  wire [SIDE_W-1:0]       in_side,
    output reg                     out_valid,
    output reg  signed [OUT_W-1:0] out_sum,
    output reg  [SIDE_W-1:0]       out_side
);
    reg signed [15:0]      fh [0:N-1]; // fh[0] = f[n-1] ... fh[N-1] = f[n-N]
    reg signed [OUT_W-1:0] sum;
    wire signed [OUT_W-1:0] f_in     = {{OUT_W-16{in_f[15]}}, in_f};
    wire signed [OUT_W-1:0] f_old    = {{OUT_W-16{fh[N-1][15]}}, fh[N-1]};
    wire signed [OUT_W-1:0] sum_next = sum + f_in - f_old;
    integer k;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            sum <= {OUT_W{1'b0}};
            for (k = 0; k < N; k = k + 1) fh[k] <= 16'sd0;
        end else if (in_valid) begin
            sum       <= sum_next;
            out_sum   <= sum_next;
            out_valid <= 1'b1;
            out_side  <= in_side;
            fh[0]     <= in_f;
            for (k = 1; k < N; k = k + 1) fh[k] <= fh[k-1];
        end
    end
endmodule
