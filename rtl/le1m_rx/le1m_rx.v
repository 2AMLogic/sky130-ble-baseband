// LE 1M receive path: non-coherent demodulator, preamble/access-address
// correlation, optional de-whitening, header length parse and CRC-24 check.
//
// Bit-exact with sim/model/le1m_rx.py (decisions 0003 and 0007): the same
// register widths, rounding and saturation, compared on the shared stimulus by
// sample index, not by clock cycle. Front-end signals follow
// spec/frontend-interface.md section 2.2. The block is strobe driven: it
// accepts one I/Q sample per `rx_valid`, with no minimum spacing, and has no
// back-pressure.
//
//   rx_i/rx_q -> FIR -> products -> CORDIC angle -> 8-sample sum -> sync search
//                                                                 -> packet engine
//
// Trace taps (`ev_*`) carry the 0007 records the model emits (bit, sync,
// tbound, cfo, crc, rssi) with the model's sample index. They are a
// verification port; nothing downstream needs them. The `gain` tap is an echo
// of the stimulus (the model has no AGC policy) and is not produced here.
//
// Not in this block (separate items): the AGC policy (agc_gain is held at
// mid-scale and never written), host interface and FIFOs, whitening beyond the
// optional de-whitener below, and synthesis/timing closure.
module le1m_rx (
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

    // configuration (static while a packet is in flight)
    input  wire [31:0]       access_address,
    input  wire [23:0]       crc_init,
    input  wire              dewhiten_en,     // 0 = none, as in the model; 1 = LE whitening
    input  wire [5:0]        chan,            // channel index for the whitening preset

    // end of capture: pulse at least 16 clk after the last rx_valid
                                              // (FIR 1 + products 1 + CORDIC 13 + integrator 1 = pipeline depth)
    input  wire              rx_flush,

    // packet status
    output wire              pkt_done,        // one-cycle pulse when the packet (or its truncated remainder) ended
    output wire              pkt_crc_ok,      // valid after pkt_done, CRC-24 check passed
    output wire              lag_overrun,     // sticky: the packet engine fell behind the history window

    // trace taps
    output wire              ev_valid,
    output wire [3:0]        ev_kind,         // 1 bit, 2 sync, 3 tbound, 4 cfo, 5 crc, 6 rssi
    output wire [31:0]       ev_index,
    output wire [23:0]       ev_value
);
    localparam HIST_W = 44;

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
    le1m_rx_fir u_fir (
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
    wire signed [18:0] int_s;
    wire        [8:0]  int_mag;
    le1m_rx_integ #(.SIDE_W(9)) u_integ (
        .clk(clk), .rst_n(rst_n), .in_valid(cor_v), .in_f(cor_angle), .in_side(cor_mag),
        .out_valid(int_v), .out_s(int_s), .out_side(int_mag));

    wire [31:0]              n_cnt;
    wire [HIST_W*19-1:0]     hist;
    wire                     found, found_flush;
    wire [31:0]              found_t;
    wire signed [31:0]       found_corr, found_sumv;
    wire [19:0]              found_w;
    le1m_rx_sync #(.HIST_W(HIST_W)) u_sync (
        .clk(clk), .rst_n(rst_n), .in_valid(int_v), .in_s(int_s), .in_mag(int_mag),
        .access_address(access_address), .flush(rx_flush), .pkt_done(pkt_done),
        .n_cnt(n_cnt), .hist(hist),
        .found(found), .found_flush(found_flush), .found_t(found_t),
        .found_corr(found_corr), .found_sumv(found_sumv), .found_w(found_w));

    le1m_rx_pkt #(.HIST_W(HIST_W)) u_pkt (
        .clk(clk), .rst_n(rst_n),
        .found(found), .found_flush(found_flush), .found_t(found_t),
        .found_corr(found_corr), .found_sumv(found_sumv), .found_w(found_w),
        .n_cnt(n_cnt), .hist(hist), .flush(rx_flush),
        .access_address(access_address), .crc_init(crc_init),
        .dewhiten_en(dewhiten_en), .chan(chan),
        .ev_valid(ev_valid), .ev_kind(ev_kind), .ev_index(ev_index), .ev_value(ev_value),
        .done(pkt_done), .crc_ok(pkt_crc_ok), .rssi_valid(rssi_valid), .rssi_lin(rssi_lin_w),
        .agc_hold(agc_hold), .lag_overrun(lag_overrun));
endmodule
