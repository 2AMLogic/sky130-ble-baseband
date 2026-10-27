// 802.15.4 O-QPSK RX stage 3: 4-sample chip integrator (model: chip_integrate),
// g[n] = f[n-3] + ... + f[n], exact in signed 18 bits, zero history at reset.
// The sideband (the RSSI magnitude) rides along unchanged.
module oqpsk_rx_integ #(
    parameter SIDE_W = 9
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                in_valid,
    input  wire signed [15:0]  in_f,
    input  wire [SIDE_W-1:0]   in_side,
    output reg                 out_valid,
    output reg  signed [17:0]  out_g,
    output reg  [SIDE_W-1:0]   out_side
);
    reg signed [15:0] fh [0:3];   // fh[0] = f[n-1] ... fh[3] = f[n-4]
    reg signed [17:0] sum;
    wire signed [17:0] f_in     = {{2{in_f[15]}}, in_f};
    wire signed [17:0] f_old    = {{2{fh[3][15]}}, fh[3]};
    wire signed [17:0] sum_next = sum + f_in - f_old;
    integer k;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            sum <= 18'sd0;
            for (k = 0; k < 4; k = k + 1) fh[k] <= 16'sd0;
        end else if (in_valid) begin
            sum       <= sum_next;
            out_g     <= sum_next;
            out_valid <= 1'b1;
            out_side  <= in_side;
            fh[0]     <= in_f;
            for (k = 1; k < 4; k = k + 1) fh[k] <= fh[k-1];
        end
    end
endmodule
