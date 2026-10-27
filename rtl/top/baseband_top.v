// Baseband top: LE 1M + IEEE 802.15.4 O-QPSK baseband with hardware lower MAC.
// Ports are those of spec/frontend-interface.md (sections 1-4: RX table 2.2, TX
// table 3.2, mode control 4) and spec/host-interface.md (section 1 APB4 slave,
// section 3 `irq`), by name. Nothing is added, renamed or dropped.
//
// Integration (rtl/top/README.md has the choices and what is not done):
//   host_top        APB registers, FIFOs, descriptors, interrupts, timestamps
//   bb_timing_regs  0x080 window: ACK / response enable, trigger compare and arm
//   bb_ctrl         STATE, fe_* sequencing, TX start check
//   bb_rx_adapt     receiver trace taps -> octets, descriptor, filters
//   bb_tx_path      FIFO / ACK frame -> le1m_tx or oqpsk_tx
//   mac_*           T_IFS response, auto-ACK, ACK wait, trigger
//   le1m_rx, oqpsk_rx   the two receivers; only the selected one gets samples
//
// CLK_MHZ is the clock in MHz (32 target, 16 fallback); the lower-MAC counts are
// derived from it. The L_DIG counts are the measured L_rx + L_tx of this
// integrated top at 32 MHz (end of packet at the input to the first tx_valid word,
// from `make test-top`; rtl/top/README.md "L_DIG_CYCLES"). The 16 MHz fallback is
// not measured: override them with the timing-and-area section 3 bounds there.
module baseband_top #(
    parameter integer CLK_MHZ          = 32,
    parameter integer LE_L_DIG_CYCLES  = 139,
    parameter integer OQ_L_DIG_CYCLES  = 41,
    parameter integer FIFO_DEPTH       = 288
) (
    input  wire        clk,
    input  wire        rst_n,

    // RX path (frontend-interface.md 2.2)
    input  wire signed [7:0] rx_i,
    input  wire signed [7:0] rx_q,
    input  wire        rx_valid,
    input  wire        rx_sat,
    output wire [5:0]  agc_gain,
    output wire        agc_gain_we,
    input  wire        agc_settled,
    output wire        agc_hold,
    output wire        rssi_valid,
    output wire [7:0]  rssi,

    // TX path (frontend-interface.md 3.2)
    output wire signed [7:0] tx_dev,
    output wire        tx_valid,
    output wire        tx_active,

    // mode control (frontend-interface.md 4)
    output wire        fe_rx_en,
    output wire        fe_tx_en,
    output wire [6:0]  fe_chan,
    output wire        fe_chan_we,
    output wire        fe_phy,
    input  wire        fe_ready,

    // APB4 slave (host-interface.md 1) and interrupt (3)
    input  wire        PSEL,
    input  wire        PENABLE,
    input  wire        PWRITE,
    input  wire [11:0] PADDR,
    input  wire [31:0] PWDATA,
    input  wire [3:0]  PSTRB,
    output wire [31:0] PRDATA,
    output wire        PREADY,
    output wire        PSLVERR,
    output wire        irq
);
    // ---- APB split: 0x080..0x0BF is served here, the rest by host_top ----------
    wire sel_t = PSEL && (PADDR[11:6] == 6'b000010);
    wire [31:0] h_prdata, t_prdata;
    wire        h_pready, h_pslverr;
    assign PRDATA  = sel_t ? t_prdata : h_prdata;
    assign PREADY  = sel_t ? 1'b1 : h_pready;
    assign PSLVERR = sel_t ? 1'b0 : h_pslverr;

    // ---- wires ---------------------------------------------------------------------
    wire        ctrl_enable, ctrl_phy, cmd_tx_start, cmd_rx_start, cmd_abort;
    wire [6:0]  ctrl_chan;
    wire [2:0]  state_i;
    wire [31:0] cfg_access_addr;
    wire [23:0] cfg_crc_init;
    wire [5:0]  cfg_whiten_ch;
    wire [47:0] cfg_own_addr;
    wire [1:0]  cfg_own_addr_type;
    wire [15:0] cfg_pan_id, cfg_short_addr;
    wire [63:0] cfg_ext_addr;
    wire        cfg_frame_pending, cfg_promiscuous;
    wire [8:0]  tx_length, tx_level;
    wire        tx_pop, tx_empty;
    wire [7:0]  tx_rdata;
    wire        rx_push, rx_full, desc_push, desc_full;
    wire [7:0]  rx_wdata;
    wire [8:0]  desc_len;
    wire [4:0]  desc_flags;
    wire        ev_sync, ev_end, ev_done_ok, ev_done_bad, ev_overflow;
    wire        tx_first, tx_fin, tx_fail, tx_refused;
    wire        ack_sent_ev, ack_timeout_ev, response_sent_ev, trigger_ev;
    wire [7:0]  fe_rssi;

    wire phy = fe_phy;

    // ---- control -------------------------------------------------------------------
    wire rx_run, tx_begin, tx_ack_mode, abort_o;
    wire resp_pending, after_tx_rx;
    wire resp_tx_req, ack_tx_req, trig_start_tx, trig_start_rx;

    bb_ctrl u_ctrl (
        .clk(clk), .rst_n(rst_n),
        .ctrl_enable(ctrl_enable), .ctrl_phy(ctrl_phy), .ctrl_chan(ctrl_chan),
        .cmd_tx_start(cmd_tx_start), .cmd_rx_start(cmd_rx_start), .cmd_abort(cmd_abort),
        .fe_ready(fe_ready), .fe_rx_en(fe_rx_en), .fe_tx_en(fe_tx_en), .fe_chan(fe_chan),
        .fe_chan_we(fe_chan_we), .fe_phy(fe_phy),
        .resp_tx_req(resp_tx_req), .ack_tx_req(ack_tx_req),
        .trig_start_tx(trig_start_tx), .trig_start_rx(trig_start_rx),
        .resp_pending(resp_pending), .after_tx_rx(after_tx_rx),
        .rx_end(ev_end), .tx_fin(tx_fin), .tx_length(tx_length), .tx_level(tx_level),
        .rx_run(rx_run), .tx_begin(tx_begin), .tx_ack_mode(tx_ack_mode),
        .tx_refused(tx_refused), .abort_o(abort_o), .state_i(state_i));

    wire phy_rst_n = rst_n & ~abort_o;

    // ---- receivers -----------------------------------------------------------------
    // rx_flush: the capture ended. Samples arrive at most every 4 clk, so 64 idle
    // clk after the last one (the pipelines need 16 / 24) marks the end.
    reg [6:0] idle_cnt;
    reg       rx_flush;
    always @(posedge clk) begin
        rx_flush <= 1'b0;
        if (!rx_run || rx_valid) idle_cnt <= 7'd0;
        else if (idle_cnt != 7'd127) begin
            idle_cnt <= idle_cnt + 7'd1;
            if (idle_cnt == 7'd64) rx_flush <= 1'b1;
        end
    end

    wire rxv    = rx_valid & rx_run;
    wire le_rst = phy_rst_n & rx_run & ~phy;
    wire oq_rst = phy_rst_n & rx_run & phy;

    wire [5:0] le_agc_gain, oq_agc_gain;
    wire       le_agc_we, oq_agc_we, le_agc_hold, oq_agc_hold, le_rssi_v, oq_rssi_v;
    wire [7:0] le_rssi, oq_rssi;
    wire [8:0] le_rssi_lin, oq_rssi_lin;
    wire       le_done, le_crc_ok, le_lag, oq_done, oq_synced, oq_crc_ok;
    wire       le_ev_v, oq_ev_v;
    wire [3:0] le_ev_k, oq_ev_k;
    wire [31:0] le_ev_i, oq_ev_i;       // sample indices: trace only
    wire [23:0] le_ev_val, oq_ev_val;

    le1m_rx u_le_rx (
        .clk(clk), .rst_n(le_rst), .rx_i(rx_i), .rx_q(rx_q), .rx_valid(rxv), .rx_sat(rx_sat),
        .agc_gain(le_agc_gain), .agc_gain_we(le_agc_we), .agc_settled(agc_settled),
        .agc_hold(le_agc_hold), .rssi_valid(le_rssi_v), .rssi(le_rssi), .rssi_lin(le_rssi_lin),
        .access_address(cfg_access_addr), .crc_init(cfg_crc_init), .dewhiten_en(1'b1),
        .chan(cfg_whiten_ch), .rx_flush(rx_flush),
        .pkt_done(le_done), .pkt_crc_ok(le_crc_ok), .lag_overrun(le_lag),
        .ev_valid(le_ev_v), .ev_kind(le_ev_k), .ev_index(le_ev_i), .ev_value(le_ev_val));

    oqpsk_rx u_oq_rx (
        .clk(clk), .rst_n(oq_rst), .rx_i(rx_i), .rx_q(rx_q), .rx_valid(rxv), .rx_sat(rx_sat),
        .agc_gain(oq_agc_gain), .agc_gain_we(oq_agc_we), .agc_settled(agc_settled),
        .agc_hold(oq_agc_hold), .rssi_valid(oq_rssi_v), .rssi(oq_rssi), .rssi_lin(oq_rssi_lin),
        .rx_flush(rx_flush),
        .pkt_done(oq_done), .pkt_synced(oq_synced), .pkt_crc_ok(oq_crc_ok),
        .ev_valid(oq_ev_v), .ev_kind(oq_ev_k), .ev_index(oq_ev_i), .ev_value(oq_ev_val));

    assign agc_gain    = phy ? oq_agc_gain : le_agc_gain;
    assign agc_gain_we = phy ? oq_agc_we : le_agc_we;
    assign agc_hold    = phy ? oq_agc_hold : le_agc_hold;
    assign rssi_valid  = phy ? oq_rssi_v : le_rssi_v;
    // verilator lint_off SYNCASYNCNET
    reg [7:0] rssi_q;                   // held until the next packet's RSSI
    always @(posedge clk) begin
        if (!rst_n) rssi_q <= 8'd0;
        else if (rssi_valid) rssi_q <= phy ? oq_rssi : le_rssi;
    end
    // verilator lint_on SYNCASYNCNET
    assign rssi    = rssi_q;
    assign fe_rssi = rssi_q;

    // ---- RX adapter ----------------------------------------------------------------
    wire fcs_ok, accept, ack_eligible, is_ack, ack_req;
    wire [7:0] seq;
    wire ack_pending;
    bb_rx_adapt u_rxa (
        .clk(clk), .rst_n(rx_run & phy_rst_n), .phy(phy),
        .ev_valid(phy ? oq_ev_v : le_ev_v), .ev_kind(phy ? oq_ev_k : le_ev_k),
        .ev_value(phy ? oq_ev_val : le_ev_val),
        .pkt_done(phy ? oq_done : le_done), .pkt_crc_ok(phy ? oq_crc_ok : le_crc_ok),
        .rx_full(rx_full), .desc_full(desc_full), .rx_push(rx_push), .rx_wdata(rx_wdata),
        .desc_push(desc_push), .desc_len(desc_len), .desc_flags(desc_flags),
        .ev_sync(ev_sync), .ev_end(ev_end), .ev_done_ok(ev_done_ok), .ev_done_bad(ev_done_bad),
        .ev_overflow(ev_overflow), .ack_pending(ack_pending),
        .cfg_access_addr(cfg_access_addr), .cfg_own_addr(cfg_own_addr),
        .cfg_own_addr_type(cfg_own_addr_type[0]), .cfg_pan_id(cfg_pan_id),
        .cfg_short_addr(cfg_short_addr), .cfg_ext_addr(cfg_ext_addr),
        .cfg_promiscuous(cfg_promiscuous),
        .fcs_ok(fcs_ok), .accept(accept), .ack_eligible(ack_eligible), .is_ack(is_ack),
        .ack_req(ack_req), .seq(seq));

    // ---- TX path -------------------------------------------------------------------
    wire [7:0] ack_seq;
    wire       ack_fp, tx_expect_ack, tx_busy;
    bb_tx_path #(.SAMPLE_CLKS(CLK_MHZ == 32 ? 2'd0 : 2'd2)) u_txp (
        .clk(clk), .rst_n(phy_rst_n), .phy(phy), .begin_tx(tx_begin), .ack_mode(tx_ack_mode),
        .ack_seq(ack_seq), .ack_fp(ack_fp),
        .cfg_access_addr(cfg_access_addr), .cfg_crc_init(cfg_crc_init),
        .cfg_whiten_ch(cfg_whiten_ch), .tx_length(tx_length), .tx_empty(tx_empty),
        .tx_rdata(tx_rdata), .tx_pop(tx_pop),
        .tx_dev(tx_dev), .tx_valid(tx_valid), .tx_active(tx_active), .tx_fin(tx_fin),
        .tx_first(tx_first), .tx_fail(tx_fail), .tx_expect_ack(tx_expect_ack), .busy(tx_busy));

    reg fail_q;
    always @(posedge clk) fail_q <= tx_fail;
    wire tx_error_ev = tx_refused | (tx_fail & ~fail_q);

    // ---- lower MAC -----------------------------------------------------------------
    wire t_ack_en, t_resp_en, t_crc_gate, t_arm, t_cancel, t_mode_tx, trig_armed;
    wire [31:0] t_cmp;
    wire [31:0] unused_tick;
    wire [4:0]  unused_sub;
    bb_timing_regs u_treg (
        .clk(clk), .rst_n(rst_n), .sel(sel_t), .penable(PENABLE), .pwrite(PWRITE),
        .paddr(PADDR), .pwdata(PWDATA), .pstrb(PSTRB), .prdata(t_prdata),
        .ack_en(t_ack_en), .resp_en(t_resp_en), .crc_gate(t_crc_gate), .trig_cmp(t_cmp),
        .trig_arm(t_arm), .trig_cancel(t_cancel), .trig_mode_tx(t_mode_tx),
        .trig_armed(trig_armed));

    mac_trigger #(.CLK_PER_US(CLK_MHZ)) u_trig (
        .clk(clk), .rst_n(rst_n), .trig_arm(t_arm), .trig_cancel(t_cancel | cmd_abort),
        .trig_cmp(t_cmp), .trig_mode_tx(t_mode_tx), .ts_tick(unused_tick), .ts_sub(unused_sub),
        .trig_armed(trig_armed), .trig_fire(trigger_ev),
        .trig_start_tx(trig_start_tx), .trig_start_rx(trig_start_rx));

    wire ifs_after_tx, ifs_busy;
    mac_le_resp #(.TIFS_CYCLES(150 * CLK_MHZ), .L_DIG_CYCLES(LE_L_DIG_CYCLES)) u_resp (
        .clk(clk), .rst_n(rst_n), .resp_enable(t_resp_en & ~phy), .crc_gate_en(t_crc_gate),
        .rx_end(ev_end & ~phy), .rx_crc_ok(fcs_ok), .rx_accept(accept),
        .tx_end(tx_fin & ~phy), .abort_req(cmd_abort),
        .resp_tx_req(resp_tx_req), .ifs_after_tx(ifs_after_tx), .ifs_busy(ifs_busy));

    mac_ack_ctrl #(.TURNAROUND_CYCLES(192 * CLK_MHZ), .L_DIG_CYCLES(OQ_L_DIG_CYCLES)) u_ack (
        .clk(clk), .rst_n(rst_n), .ack_enable(t_ack_en & phy), .fp_bit(cfg_frame_pending),
        .rx_end(ev_end & phy), .rx_fcs_ok(fcs_ok), .rx_ack_req(ack_req), .rx_is_ack(is_ack),
        .rx_ack_eligible(ack_eligible), .rx_seq(seq), .abort_req(cmd_abort),
        .ack_tx_req(ack_tx_req), .ack_seq(ack_seq), .ack_fp(ack_fp), .ack_pending(ack_pending));

    wire ackwait_busy, ev_ack_received;
    mac_ackwait #(.ACKWAIT_CYCLES(864 * CLK_MHZ)) u_aw (
        .clk(clk), .rst_n(rst_n), .tx_frame_end(tx_fin & phy & ~tx_ack_mode),
        .tx_expect_ack(tx_expect_ack), .ack_rx(ev_end & phy & is_ack & fcs_ok),
        .abort_req(cmd_abort), .ackwait_busy(ackwait_busy), .ev_ack_received(ev_ack_received),
        .ev_ack_timeout(ack_timeout_ev));

    assign ack_sent_ev      = ack_tx_req;
    assign response_sent_ev = resp_tx_req;
    // the LE T_IFS timer also runs after a plain host TX; it only means "open RX"
    // when the timed response is enabled (TIMING_CTRL.RESP_EN)
    wire le_ifs = ifs_busy & t_resp_en & ~phy;
    assign resp_pending     = le_ifs | ack_pending;
    assign after_tx_rx      = le_ifs | ackwait_busy;

    // ---- host interface ------------------------------------------------------------
    host_top #(.FIFO_DEPTH(FIFO_DEPTH), .CLK_PER_US(CLK_MHZ)) u_host (
        .clk(clk), .rst_n_in(rst_n),
        .psel(PSEL & ~sel_t), .penable(PENABLE), .pwrite(PWRITE), .paddr(PADDR),
        .pwdata(PWDATA), .pstrb(PSTRB), .prdata(h_prdata), .pready(h_pready),
        .pslverr(h_pslverr), .irq(irq),
        .ctrl_enable(ctrl_enable), .ctrl_phy(ctrl_phy), .ctrl_chan(ctrl_chan),
        .cmd_tx_start(cmd_tx_start), .cmd_rx_start(cmd_rx_start), .cmd_abort(cmd_abort),
        .state_i(state_i),
        .cfg_access_addr(cfg_access_addr), .cfg_crc_init(cfg_crc_init),
        .cfg_whiten_ch(cfg_whiten_ch), .cfg_own_addr(cfg_own_addr),
        .cfg_own_addr_type(cfg_own_addr_type), .cfg_pan_id(cfg_pan_id),
        .cfg_short_addr(cfg_short_addr), .cfg_ext_addr(cfg_ext_addr),
        .cfg_frame_pending(cfg_frame_pending), .cfg_promiscuous(cfg_promiscuous),
        .tx_length(tx_length), .tx_level(tx_level), .tx_pop(tx_pop), .tx_rdata(tx_rdata),
        .tx_empty(tx_empty),
        .rx_push(rx_push), .rx_wdata(rx_wdata), .rx_full(rx_full),
        .desc_push(desc_push), .desc_len_in(desc_len), .desc_flags_in(desc_flags),
        .desc_full(desc_full),
        .rx_sync(ev_sync), .rx_end(ev_end), .rx_done_ok(ev_done_ok), .rx_done_bad(ev_done_bad),
        .rx_overflow(ev_overflow), .tx_start(tx_first), .tx_done(tx_fin), .tx_error(tx_error_ev),
        .ack_sent(ack_sent_ev), .ack_timeout(ack_timeout_ev), .response_sent(response_sent_ev),
        .trigger(trigger_ev),
        .fe_rssi(fe_rssi), .fe_agc_settled(agc_settled));

    wire _unused = &{1'b0, unused_tick, unused_sub, ifs_after_tx, ev_ack_received, le_lag,
                     oq_synced, le_ev_i, oq_ev_i, le_rssi_lin, oq_rssi_lin, tx_busy, cfg_own_addr_type[1]};
endmodule
