// 802.15.4 O-QPSK receive path: non-coherent demodulator, chip-rate
// despreader, preamble/SFD detect, PHR length parse and FCS check.
//
// Bit-exact with sim/model/oqpsk_rx.py (decisions 0003 and 0007): the same
// register widths, rounding and saturation, compared on the shared stimulus by
// sample index, not by clock cycle. Front-end signals follow
// spec/frontend-interface.md section 2.2 at the target operating point (8 Msps,
// 4 samples per chip); the 4 Msps fallback is not modelled and not supported.
// The block is strobe driven: it accepts one I/Q sample per `rx_valid`, with no
// minimum spacing, and has no back-pressure.
//
//   rx_i/rx_q -> FIR -> products -> CORDIC angle -> 4-sample chip sum
//             -> 16 correlators x 31 taps -> preamble/SFD search -> packet engine
//
// The discriminator products and the CORDIC are the LE 1M receiver's modules,
// instantiated unchanged (rtl/le1m_rx/le1m_rx_disc.v, le1m_rx_cordic.v): the
// model shares le1m_rx.discriminate between the two PHYs. The FIR, the chip
// integrator and everything after it are new.
//
// One packet per capture, as the model: after the SFD the engine decodes one
// packet (or runs to rx_flush), then stays quiet until rst_n.
//
// Trace taps (`ev_*`) carry the 0007 records the model emits (sync, octet,
// tbound, crc, rssi) with the model's sample index. They are a verification
// port; nothing downstream needs them. `ev_kind`: 2 sync, 3 tbound, 5 crc,
// 6 rssi, 7 octet. The `gain` tap is an echo of the stimulus and is not
// produced here. There is no `cfo` tap: the model makes no offset estimate.
//
// Not in this block (separate items): the AGC policy (agc_gain is held at
// mid-scale and never written), host interface and FIFOs, auto-ACK and address
// filtering (rtl/mac/), and synthesis/timing closure.
module oqpsk_rx (
    input  wire              clk,
    input  wire              rst_n,           // active-low synchronous reset

    // front end, spec/frontend-interface.md 2.2
    input  wire signed [7:0] rx_i,
    input  wire signed [7:0] rx_q,
    input  wire              rx_valid,
    input  wire              rx_sat,
    output wire [5:0]        agc_gain,
    output wire              agc_gain_we,
    input  wire              agc_settled,
    output wire              agc_hold,
    output wire              rssi_valid,
    output wire [7:0]        rssi,            // placeholder: rssi_lin saturated to 8 bits
    output wire [8:0]        rssi_lin,        // the model's linear RSSI, valid with rssi_valid

    // end of capture: pulse at least 24 clk after the last rx_valid
    // (FIR 1 + products 1 + CORDIC 13 + chip sum 1 + correlators 2 = pipeline depth 18)
    input  wire              rx_flush,

    // packet status
    output wire              pkt_done,        // one-cycle pulse when the packet (or what the capture held) ended
    output wire              pkt_synced,      // sticky: an SFD was found
    output wire              pkt_crc_ok,      // valid after pkt_done, FCS check passed

    // trace taps
    output wire              ev_valid,
    output wire [3:0]        ev_kind,         // 2 sync, 3 tbound, 5 crc, 6 rssi, 7 octet
    output wire [31:0]       ev_index,
    output wire [23:0]       ev_value
);
    // --- front-end hooks ---------------------------------------------------
    assign agc_gain    = 6'd32;
    assign agc_gain_we = 1'b0;
    wire _unused_fe = &{1'b0, rx_sat, agc_settled};

    wire [8:0] rssi_lin_w;
    assign rssi_lin = rssi_lin_w;
    assign rssi     = (rssi_lin_w > 9'd255) ? 8'd255 : rssi_lin_w[7:0];

    // --- stages ------------------------------------------------------------
    wire              fir_v;
    wire signed [8:0] fir_i, fir_q;
    wire        [8:0] fir_mag;
    oqpsk_rx_fir u_fir (
        .clk(clk), .rst_n(rst_n), .in_valid(rx_valid), .in_i(rx_i), .in_q(rx_q),
        .out_valid(fir_v), .out_i(fir_i), .out_q(fir_q), .out_mag(fir_mag));

    wire               dsc_v;
    wire signed [18:0] dsc_re, dsc_im;
    wire        [8:0]  dsc_mag;
    le1m_rx_disc u_disc (
        .clk(clk), .rst_n(rst_n), .in_valid(fir_v), .in_i(fir_i), .in_q(fir_q), .in_mag(fir_mag),
        .out_valid(dsc_v), .out_re(dsc_re), .out_im(dsc_im), .out_mag(dsc_mag));

    wire               cor_v;
    wire signed [15:0] cor_angle;
    wire        [8:0]  cor_mag;
    le1m_rx_cordic #(.SIDE_W(9)) u_cordic (
        .clk(clk), .rst_n(rst_n), .in_valid(dsc_v), .in_x(dsc_re), .in_y(dsc_im), .in_side(dsc_mag),
        .out_valid(cor_v), .out_angle(cor_angle), .out_side(cor_mag));

    wire               int_v;
    wire signed [17:0] int_g;
    wire        [8:0]  int_mag;
    oqpsk_rx_integ #(.SIDE_W(9)) u_integ (
        .clk(clk), .rst_n(rst_n), .in_valid(cor_v), .in_f(cor_angle), .in_side(cor_mag),
        .out_valid(int_v), .out_g(int_g), .out_side(int_mag));

    wire              c_valid;
    wire [31:0]       c_n;
    wire [16*23-1:0]  c_vec;
    wire [3:0]        c_best;
    wire              c_ok;
    wire [16:0]       c_rsum;
    oqpsk_rx_corr #(.SIDE_W(9)) u_corr (
        .clk(clk), .rst_n(rst_n), .in_valid(int_v), .in_g(int_g), .in_mag(int_mag),
        .o_valid(c_valid), .o_n(c_n), .o_vec(c_vec), .o_best(c_best), .o_ok(c_ok), .o_rsum(c_rsum));

    wire found;
    oqpsk_rx_sync u_sync (
        .clk(clk), .rst_n(rst_n), .c_valid(c_valid), .c_best(c_best), .c_ok(c_ok),
        .c_corr0($signed(c_vec[22:0])), .found(found));

    oqpsk_rx_pkt u_pkt (
        .clk(clk), .rst_n(rst_n),
        .c_valid(c_valid), .c_n(c_n), .c_vec(c_vec), .c_best(c_best), .c_rsum(c_rsum),
        .found(found), .flush(rx_flush),
        .ev_valid(ev_valid), .ev_kind(ev_kind), .ev_index(ev_index), .ev_value(ev_value),
        .pkt_done(pkt_done), .pkt_synced(pkt_synced), .pkt_crc_ok(pkt_crc_ok),
        .rssi_valid(rssi_valid), .rssi_lin(rssi_lin_w), .agc_hold(agc_hold));
endmodule
