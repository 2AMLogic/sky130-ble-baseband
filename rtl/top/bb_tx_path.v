// TX path: host TX FIFO and automatic-ACK frame to the two modulators
// (spec/host-interface.md section 2 "TX FIFO", frontend-interface.md 3.2).
//
//   LE 1M   le1m_tx pulls PDU octets straight from the FIFO (`tx_length` octets,
//           header included, as le1m_tx's pdu_len).
//   15.4    oqpsk_tx reads the payload through an asynchronous-read port, so the
//           FIFO octets are first copied into a 125-octet buffer (one per clk),
//           then oqpsk_tx starts. The FCS is appended by oqpsk_tx. An automatic
//           ACK is the 3-octet payload {FC lo = 0x02 | frame-pending<<4, 0x00,
//           sequence} built here instead of the FIFO (mac_ack_ctrl, row 11).
// `tx_tick` for oqpsk_tx is a free-running divide-by-4 of the 32 MHz clock
// (8 Msps); at 16 MHz the interface rate halves, so SAMPLE_CLKS is a parameter.
module bb_tx_path #(
    parameter [1:0] SAMPLE_CLKS = 2'd0   // clk per sample slot: 4 at 32 MHz, 2 at 16 MHz (0 stands for 4)
) (
    input  wire        clk,
    input  wire        rst_n,           // low also aborts a running transmission
    input  wire        phy,
    input  wire        begin_tx,        // one-cycle pulse
    input  wire        ack_mode,        // 15.4: send the automatic ACK instead of the FIFO
    input  wire [7:0]  ack_seq,
    input  wire        ack_fp,

    input  wire [31:0] cfg_access_addr,
    input  wire [23:0] cfg_crc_init,
    input  wire [5:0]  cfg_whiten_ch,
    input  wire [8:0]  tx_length,
    input  wire        tx_empty,
    input  wire [7:0]  tx_rdata,
    output wire        tx_pop,

    output wire signed [7:0] tx_dev,
    output wire        tx_valid,
    output wire        tx_active,
    output reg         tx_fin,          // one-cycle pulse when the packet is over
    output wire        tx_first,        // one-cycle pulse when tx_active rises
    output wire        tx_fail,         // underrun / refused start
    output wire        tx_expect_ack,   // 15.4 host frame asked for an ACK (FC bit 5)
    output wire        busy
);
    // ---- LE 1M ----------------------------------------------------------------
    wire        le_pdu_ready, le_busy, le_underrun, le_valid, le_active;
    wire [7:0]  le_dev;
    wire        le_pop = le_pdu_ready & ~tx_empty & ~phy;
    le1m_tx u_le (
        .clk(clk), .rst_n(rst_n), .start(begin_tx & ~phy),
        .access_address(cfg_access_addr), .channel(cfg_whiten_ch), .crc_init(cfg_crc_init),
        .pdu_len(tx_length), .pdu_ready(le_pdu_ready), .pdu_valid(~tx_empty), .pdu_data(tx_rdata),
        .tx_dev(le_dev), .tx_valid(le_valid), .tx_active(le_active),
        .busy(le_busy), .underrun(le_underrun));

    // ---- 802.15.4 -----------------------------------------------------------------
    reg [7:0] tbuf [0:124];
    reg [1:0] cstate;                   // 0 idle, 1 copying
    reg [8:0] ccnt;
    reg       oq_start;
    reg [6:0] oq_len;
    reg       ack_sel;
    reg [7:0] ack_b0, ack_b1, ack_b2;
    wire [6:0] psdu_idx;
    wire       oq_active, oq_valid, oq_done, oq_reject;
    wire signed [7:0] oq_dev;
    reg  [1:0] tk;
    wire [1:0] LAST = SAMPLE_CLKS - 2'd1;      // 0 - 1 = 3 for the 4-clk grid

    wire [7:0] psdu_data = ack_sel ? ((psdu_idx == 7'd0) ? ack_b0 : (psdu_idx == 7'd1) ? ack_b1 : ack_b2)
                                   : tbuf[psdu_idx];
    wire       oq_pop = (cstate == 2'd1) && phy;

    oqpsk_tx u_oq (
        .clk(clk), .rst_n(rst_n), .tx_start(oq_start), .tx_len(oq_len),
        .psdu_idx(psdu_idx), .psdu_data(psdu_data), .tx_tick(tk == LAST),
        .tx_dev(oq_dev), .tx_valid(oq_valid), .tx_active(oq_active),
        .tx_done(oq_done), .tx_reject(oq_reject));

    always @(posedge clk) begin
        oq_start <= 1'b0;
        tk       <= (tk == LAST) ? 2'd0 : tk + 2'd1;
        if (!rst_n) begin
            cstate <= 2'd0;
            ccnt   <= 9'd0;
            oq_len <= 7'd0;
            ack_sel <= 1'b0;
            ack_b0 <= 8'd0; ack_b1 <= 8'd0; ack_b2 <= 8'd0;
            tk     <= 2'd0;
        end else begin
            if (begin_tx && phy) begin
                if (ack_mode) begin
                    ack_sel  <= 1'b1;
                    ack_b0   <= {3'b000, ack_fp, 4'b0010};
                    ack_b1   <= 8'h00;
                    ack_b2   <= ack_seq;
                    oq_len   <= 7'd3;
                    oq_start <= 1'b1;
                end else begin
                    ack_sel <= 1'b0;
                    oq_len  <= tx_length[6:0];
                    ccnt    <= 9'd0;
                    if (tx_length == 9'd0) oq_start <= 1'b1;
                    else                   cstate <= 2'd1;
                end
            end
            if (cstate == 2'd1) begin
                tbuf[ccnt[6:0]] <= tx_rdata;
                ccnt <= ccnt + 9'd1;
                if (ccnt + 9'd1 == tx_length) begin
                    cstate   <= 2'd0;
                    oq_start <= 1'b1;
                end
            end
        end
    end

    assign tx_pop = le_pop | oq_pop;
    assign tx_dev    = phy ? oq_dev : le_dev;
    assign tx_valid  = phy ? oq_valid : le_valid;
    assign tx_active = phy ? oq_active : le_active;
    assign tx_fail   = (le_underrun & le_busy) | oq_reject;
    assign tx_expect_ack = phy && !ack_sel && tbuf[0][5];
    assign busy      = le_busy | oq_active | (cstate != 2'd0) | oq_start;

    // end of packet: LE has no done strobe, so use the fall of tx_active
    reg act_q;
    always @(posedge clk) begin
        act_q  <= tx_active;
        tx_fin <= phy ? oq_done : (act_q & ~le_active);
    end
    assign tx_first = tx_active & ~act_q;

    wire _unused = &{1'b0, oq_pop};
endmodule
