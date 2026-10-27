// Host interface top: APB registers, TX/RX octet FIFOs, RX descriptor FIFO,
// interrupts and timestamps (spec/host-interface.md). MAC/PHY blocks connect as
// ports; wiring them to this block is the top-level integration issue.
//
// Reset: asynchronous assert, synchronous release (two-flop release on clk).
// Descriptor contract: desc_push is asserted at least one cycle after rx_sync and
// rx_end so the start/end timestamps are already captured; RSSI is sampled from
// fe_rssi at the push.
module host_top #(
    parameter FIFO_DEPTH  = 288,
    parameter CLK_PER_US  = 32
) (
    input  wire        clk,
    input  wire        rst_n_in,

    // APB4 slave
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [11:0] paddr,
    input  wire [31:0] pwdata,
    input  wire [3:0]  pstrb,
    output wire [31:0] prdata,
    output wire        pready,
    output wire        pslverr,
    output wire        irq,

    // control / status to MAC
    output wire        ctrl_enable,
    output wire        ctrl_phy,
    output wire [6:0]  ctrl_chan,
    output wire        cmd_tx_start,
    output wire        cmd_rx_start,
    output wire        cmd_abort,
    input  wire [2:0]  state_i,

    // link configuration to MAC/PHY
    output wire [31:0] cfg_access_addr,
    output wire [23:0] cfg_crc_init,
    output wire [5:0]  cfg_whiten_ch,
    output wire [47:0] cfg_own_addr,
    output wire [1:0]  cfg_own_addr_type,
    output wire [15:0] cfg_pan_id,
    output wire [15:0] cfg_short_addr,
    output wire [63:0] cfg_ext_addr,
    output wire        cfg_frame_pending,
    output wire        cfg_promiscuous,

    // TX FIFO, consumer side (modulator/MAC)
    output wire [8:0]  tx_length,
    output wire [8:0]  tx_level,
    input  wire        tx_pop,
    output wire [7:0]  tx_rdata,
    output wire        tx_empty,

    // RX FIFO, producer side (demodulator/MAC)
    input  wire        rx_push,
    input  wire [7:0]  rx_wdata,
    output wire        rx_full,

    // RX descriptor push (length, flags: [0] crc_ok [1] truncated [2] addr_match [3] ack_sent [4] phy)
    input  wire        desc_push,
    input  wire [8:0]  desc_len_in,
    input  wire [4:0]  desc_flags_in,
    output wire        desc_full,

    // event strobes (one cycle each)
    input  wire        rx_sync,
    input  wire        rx_end,
    input  wire        rx_done_ok,
    input  wire        rx_done_bad,
    input  wire        rx_overflow,
    input  wire        tx_start,
    input  wire        tx_done,
    input  wire        tx_error,
    input  wire        ack_sent,
    input  wire        ack_timeout,
    input  wire        response_sent,
    input  wire        trigger,

    // front end
    input  wire [7:0]  fe_rssi,
    input  wire        fe_agc_settled
);
    // ---- reset synchronizer --------------------------------------------------------------
    // verilator lint_off SYNCASYNCNET
    reg [1:0] rst_sync;  // async-assert, sync-release: used as async reset downstream by design
    // verilator lint_on SYNCASYNCNET
    always @(posedge clk or negedge rst_n_in) begin
        if (!rst_n_in) rst_sync <= 2'b00;
        else           rst_sync <= {rst_sync[0], 1'b1};
    end
    wire rst_n = rst_sync[1];

    // ---- registers -----------------------------------------------------------------------
    wire        cmd_tx_flush, cmd_rx_flush;
    wire [9:0]  int_raw, int_enable, int_status;
    wire [1:0]  err_status;
    wire [9:0]  irq_raw_clr, irq_stat_clr;
    wire [1:0]  irq_err_clr;
    wire        irq_en_we;
    wire [31:0] wd, wmask;
    wire        tx_push, rx_pop, desc_pop, ts_rd_tick;
    wire [7:0]  tx_wdata, rx_rdata;
    wire [8:0]  rx_level;
    wire [2:0]  desc_count;
    wire [95:0] desc_head;
    wire [31:0] ts_tick;
    wire [4:0]  ts_sub, ts_sub_latched;
    wire [36:0] cap_rx_start, cap_rx_end, cap_tx_start, cap_tx_end, cap_trigger;

    host_regs u_regs (
        .clk(clk), .rst_n(rst_n),
        .psel(psel), .penable(penable), .pwrite(pwrite), .paddr(paddr),
        .pwdata(pwdata), .pstrb(pstrb), .prdata(prdata), .pready(pready), .pslverr(pslverr),
        .ctrl_enable(ctrl_enable), .ctrl_phy(ctrl_phy), .ctrl_chan(ctrl_chan),
        .cmd_tx_start(cmd_tx_start), .cmd_rx_start(cmd_rx_start), .cmd_abort(cmd_abort),
        .cmd_tx_flush(cmd_tx_flush), .cmd_rx_flush(cmd_rx_flush), .state_i(state_i),
        .int_raw(int_raw), .int_enable(int_enable), .int_status(int_status),
        .err_status(err_status),
        .irq_raw_clr(irq_raw_clr), .irq_stat_clr(irq_stat_clr), .irq_err_clr(irq_err_clr),
        .irq_en_we(irq_en_we), .wd(wd), .wmask(wmask),
        .cfg_access_addr(cfg_access_addr), .cfg_crc_init(cfg_crc_init),
        .cfg_whiten_ch(cfg_whiten_ch), .cfg_own_addr(cfg_own_addr),
        .cfg_own_addr_type(cfg_own_addr_type), .cfg_pan_id(cfg_pan_id),
        .cfg_short_addr(cfg_short_addr), .cfg_ext_addr(cfg_ext_addr),
        .cfg_frame_pending(cfg_frame_pending), .cfg_promiscuous(cfg_promiscuous),
        .tx_push(tx_push), .tx_wdata(tx_wdata), .tx_length(tx_length), .tx_level(tx_level),
        .rx_pop(rx_pop), .rx_rdata(rx_rdata), .rx_level(rx_level),
        .desc_count(desc_count), .desc_len(desc_head[8:0]), .desc_flags(desc_head[13:9]),
        .desc_rssi(desc_head[21:14]), .desc_ts_start(desc_head[58:22]),
        .desc_ts_end(desc_head[95:59]), .desc_pop(desc_pop),
        .ts_tick(ts_tick), .ts_sub_latched(ts_sub_latched), .ts_rd_tick(ts_rd_tick),
        .cap_tx_start(cap_tx_start), .cap_tx_end(cap_tx_end), .cap_trigger(cap_trigger),
        .fe_rssi(fe_rssi), .fe_agc_settled(fe_agc_settled)
    );

    // ---- FIFOs ---------------------------------------------------------------------------
    wire tx_overflow, tx_underflow_unused, rx_fifo_overflow, rx_underflow;
    wire rx_full_unused_empty, tx_full_unused;
    wire [8:0] tx_level_w;
    assign tx_level = tx_level_w;

    host_fifo #(.DEPTH(FIFO_DEPTH)) u_tx_fifo (
        .clk(clk), .rst_n(rst_n), .flush(cmd_tx_flush),
        .push(tx_push), .wdata(tx_wdata), .pop(tx_pop), .rdata(tx_rdata),
        .level(tx_level_w), .full(tx_full_unused), .empty(tx_empty),
        .overflow(tx_overflow), .underflow(tx_underflow_unused)
    );

    host_fifo #(.DEPTH(FIFO_DEPTH)) u_rx_fifo (
        .clk(clk), .rst_n(rst_n), .flush(cmd_rx_flush),
        .push(rx_push), .wdata(rx_wdata), .pop(rx_pop), .rdata(rx_rdata),
        .level(rx_level), .full(rx_full), .empty(rx_full_unused_empty),
        .overflow(rx_fifo_overflow), .underflow(rx_underflow)
    );

    // ---- descriptor FIFO -----------------------------------------------------------------
    wire desc_overflow, desc_empty_unused;
    wire [95:0] desc_wdata = {cap_rx_end, cap_rx_start, fe_rssi, desc_flags_in, desc_len_in};

    host_desc_fifo #(.W(96)) u_desc_fifo (
        .clk(clk), .rst_n(rst_n), .flush(cmd_rx_flush),
        .push(desc_push), .wdata(desc_wdata), .pop(desc_pop), .head(desc_head),
        .count(desc_count), .full(desc_full), .empty(desc_empty_unused),
        .overflow(desc_overflow)
    );

    // ---- interrupts ----------------------------------------------------------------------
    wire [9:0] ev = {trigger, response_sent, ack_timeout, ack_sent, tx_error, tx_done,
                     rx_overflow | rx_fifo_overflow | desc_overflow,
                     rx_done_bad, rx_done_ok, rx_sync};

    host_irq u_irq (
        .clk(clk), .rst_n(rst_n), .ev(ev), .err_ev({tx_overflow, rx_underflow}),
        .raw_clr(irq_raw_clr), .stat_clr(irq_stat_clr), .err_clr(irq_err_clr),
        .en_we(irq_en_we), .wd(wd), .wmask(wmask),
        .int_raw(int_raw), .int_enable(int_enable), .int_status(int_status),
        .err_status(err_status), .irq(irq)
    );

    // ---- timestamps ----------------------------------------------------------------------
    host_timestamp #(.CLK_PER_US(CLK_PER_US)) u_ts (
        .clk(clk), .rst_n(rst_n), .rd_tick(ts_rd_tick),
        .tick(ts_tick), .sub(ts_sub), .sub_latched(ts_sub_latched),
        .ev_rx_sync(rx_sync), .ev_rx_end(rx_end), .ev_tx_start(tx_start),
        .ev_tx_end(tx_done), .ev_trigger(trigger),
        .cap_rx_start(cap_rx_start), .cap_rx_end(cap_rx_end),
        .cap_tx_start(cap_tx_start), .cap_tx_end(cap_tx_end), .cap_trigger(cap_trigger)
    );

    wire _unused = &{1'b0, ts_sub, tx_underflow_unused, tx_full_unused, rx_full_unused_empty,
                     desc_empty_unused};
endmodule
