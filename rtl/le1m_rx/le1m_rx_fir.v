// LE 1M RX stage 1: channel FIR on I and Q (model: channel_filter), plus the
// alpha-max-beta-min magnitude of the filtered pair that the RSSI window sums
// (model: _rssi). 11-tap symmetric FIR 1 4 9 16 22 24 22 16 9 4 1 (sum 128),
// causal, zero history at reset, (acc + 64) >> 7 round half up, saturated to
// signed 9 bits. Strobe driven: one output per in_valid, one clk later.
module le1m_rx_fir (
    input  wire              clk,
    input  wire              rst_n,   // active-low synchronous reset
    input  wire              in_valid,
    input  wire signed [7:0] in_i,
    input  wire signed [7:0] in_q,
    output reg               out_valid,
    output reg  signed [8:0] out_i,
    output reg  signed [8:0] out_q,
    output reg         [8:0] out_mag  // max(|i|,|q|) + (min(|i|,|q|) >> 1), <= 384
);
    // hi0 is the previous input sample, hi9 the one ten back
    reg signed [7:0] hi0, hi1, hi2, hi3, hi4, hi5, hi6, hi7, hi8, hi9;
    reg signed [7:0] hq0, hq1, hq2, hq3, hq4, hq5, hq6, hq7, hq8, hq9;

    wire signed [16:0] acc_i =
          1 * in_i + 4 * hi0 + 9 * hi1 + 16 * hi2 + 22 * hi3 + 24 * hi4
        + 22 * hi5 + 16 * hi6 + 9 * hi7 + 4 * hi8 + 1 * hi9 + 17'sd64;
    wire signed [16:0] acc_q =
          1 * in_q + 4 * hq0 + 9 * hq1 + 16 * hq2 + 22 * hq3 + 24 * hq4
        + 22 * hq5 + 16 * hq6 + 9 * hq7 + 4 * hq8 + 1 * hq9 + 17'sd64;

    // acc >> 7 is within [-128, 128], so the 9-bit saturation never fires for
    // 8-bit inputs; it is kept because the model states it.
    wire signed [16:0] rnd_i = acc_i >>> 7;
    wire signed [16:0] rnd_q = acc_q >>> 7;
    wire signed [8:0]  sat_i = (rnd_i > 17'sd255) ? 9'sd255 : (rnd_i < -17'sd256) ? -9'sd256 : rnd_i[8:0];
    wire signed [8:0]  sat_q = (rnd_q > 17'sd255) ? 9'sd255 : (rnd_q < -17'sd256) ? -9'sd256 : rnd_q[8:0];

    wire [8:0] abs_i = sat_i[8] ? -sat_i : sat_i;   // |-256| = 256 fits in 9 bits unsigned
    wire [8:0] abs_q = sat_q[8] ? -sat_q : sat_q;
    wire [8:0] mx = (abs_i > abs_q) ? abs_i : abs_q;
    wire [8:0] mn = (abs_i > abs_q) ? abs_q : abs_i;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            {hi0, hi1, hi2, hi3, hi4, hi5, hi6, hi7, hi8, hi9} <= 80'd0;
            {hq0, hq1, hq2, hq3, hq4, hq5, hq6, hq7, hq8, hq9} <= 80'd0;
        end else if (in_valid) begin
            {hi0, hi1, hi2, hi3, hi4, hi5, hi6, hi7, hi8, hi9} <= {in_i, hi0, hi1, hi2, hi3, hi4, hi5, hi6, hi7, hi8};
            {hq0, hq1, hq2, hq3, hq4, hq5, hq6, hq7, hq8, hq9} <= {in_q, hq0, hq1, hq2, hq3, hq4, hq5, hq6, hq7, hq8};
            out_valid <= 1'b1;
            out_i     <= sat_i;
            out_q     <= sat_q;
            out_mag   <= mx + (mn >> 1);
        end
    end
endmodule
