// LE 1M RX stage 2a: delay-and-multiply products of the filtered samples
// (model: discriminate, before the angle). re = I*I' + Q*Q', im = Q*I' - I*Q'
// with I', Q' the previous filtered sample (zero before the first), exact in
// signed 19 bits. The first sample sees a zero predecessor, so re = im = 0 and
// the angle is the forced zero the model specifies for sample 0.
module le1m_rx_disc (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    input  wire signed [8:0]  in_i,
    input  wire signed [8:0]  in_q,
    input  wire        [8:0]  in_mag,   // sideband, passed through
    output reg                out_valid,
    output reg  signed [18:0] out_re,
    output reg  signed [18:0] out_im,
    output reg         [8:0]  out_mag
);
    reg signed [8:0] prev_i, prev_q;

    always @(posedge clk) begin
        out_valid <= 1'b0;
        if (!rst_n) begin
            prev_i <= 9'sd0;
            prev_q <= 9'sd0;
        end else if (in_valid) begin
            prev_i    <= in_i;
            prev_q    <= in_q;
            out_valid <= 1'b1;
            out_re    <= in_i * prev_i + in_q * prev_q;
            out_im    <= in_q * prev_i - in_i * prev_q;
            out_mag   <= in_mag;
        end
    end
endmodule
