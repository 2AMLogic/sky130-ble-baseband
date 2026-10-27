// 802.15.4 O-QPSK RX stage 1: channel FIR on I and Q (model:
// oqpsk_rx.channel_filter), plus the alpha-max-beta-min magnitude of the
// filtered pair that the RSSI window sums (model: le1m_rx._rssi). 5-tap
// symmetric FIR 1 4 6 4 1 (sum 16), causal, zero history at reset,
// (acc + 8) >> 4 round half up, saturated to signed 9 bits. Strobe driven: one
// output per in_valid, one clk later. Same ports as le1m_rx_fir.
module oqpsk_rx_fir (
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
    // hi0 is the previous input sample, hi3 the one four back
    reg signed [7:0] hi0, hi1, hi2, hi3;
    reg signed [7:0] hq0, hq1, hq2, hq3;

    wire signed [13:0] acc_i = 1 * in_i + 4 * hi0 + 6 * hi1 + 4 * hi2 + 1 * hi3 + 14'sd8;
    wire signed [13:0] acc_q = 1 * in_q + 4 * hq0 + 6 * hq1 + 4 * hq2 + 1 * hq3 + 14'sd8;

    // acc >> 4 is within [-128, 128], so the 9-bit saturation never fires for
    // 8-bit inputs; it is kept because the model states it.
    wire signed [13:0] rnd_i = acc_i >>> 4;
    wire signed [13:0] rnd_q = acc_q >>> 4;
    wire signed [8:0]  sat_i = (rnd_i > 14'sd255) ? 9'sd255 : (rnd_i < -14'sd256) ? -9'sd256 : rnd_i[8:0];
    wire signed [8:0]  sat_q = (rnd_q > 14'sd255) ? 9'sd255 : (rnd_q < -14'sd256) ? -9'sd256 : rnd_q[8:0];

    wire [8:0] abs_i = sat_i[8] ? -sat_i : sat_i;   // |-256| = 256 fits in 9 bits unsigned
    wire [8:0] abs_q = sat_q[8] ? -sat_q : sat_q;
    wire [8:0] mx = (abs_i > abs_q) ? abs_i : abs_q;
    wire [8:0] mn = (abs_i > abs_q) ? abs_q : abs_i;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            {hi0, hi1, hi2, hi3} <= 32'd0;
            {hq0, hq1, hq2, hq3} <= 32'd0;
        end else if (in_valid) begin
            {hi0, hi1, hi2, hi3} <= {in_i, hi0, hi1, hi2};
            {hq0, hq1, hq2, hq3} <= {in_q, hq0, hq1, hq2};
            out_valid <= 1'b1;
            out_i     <= sat_i;
            out_q     <= sat_q;
            out_mag   <= mx + (mn >> 1);
        end
    end
endmodule
