// RX adapter: turns the receivers' trace taps into the host-side octet stream
// (spec/host-interface.md sections 2 and 3, rows "RX FIFO", "Packet descriptor",
// "Overflow and underflow behaviour") and the lower-MAC inputs (decision 0006
// rows 11, 13, 14).
//
// Neither receiver has an octet port; both leave their results on the ev_* bus.
//   LE 1M   kind 1 = one de-whitened bit per symbol (PDU bits, then 24 CRC bits),
//           LSB first; octets are assembled here and the CRC bits are dropped.
//           The FIFO receives the whole PDU: 2 header octets then the payload.
//   15.4    kind 7 = one PSDU octet, FCS included. The FCS is dropped with a
//           two-octet delay line, so it never reaches the FIFO.
//   both    kind 2 = sync (RX_SYNC); `pkt_done` = end of packet (rx_end).
// Descriptor length is the number of octets that went into the FIFO.
//
// Not decided by the spec, chosen here (rtl/top/README.md, "Choices"):
//   - the RX FIFO holds a packet's octets as provisional until the final accept
//     decision (host_fifo HOLD = 1): a CRC-good packet the address filter rejects
//     is rolled back out of the FIFO, gets no descriptor, and raises RX_DONE_BAD
//     (spec/host-interface.md section 3, operator ruling on #73); every other
//     packet, CRC-bad ones included, is committed and delivered as before;
//   - the received access address is not observable, so the LE AA compare is
//     fed the configured one (the receiver only syncs on it).
module bb_rx_adapt (
    input  wire        clk,
    input  wire        rst_n,            // low = clear all per-packet state
    input  wire        phy,              // 0 LE 1M, 1 802.15.4

    input  wire        ev_valid,
    input  wire [3:0]  ev_kind,
    input  wire [23:0] ev_value,
    input  wire        pkt_done,
    input  wire        pkt_crc_ok,

    // host side
    input  wire        rx_full,
    input  wire        desc_full,
    output reg         rx_push,
    output reg  [7:0]  rx_wdata,
    output wire        rx_commit,        // with ev_end: publish this packet's octets
    output wire        rx_rollback,      // with ev_end: discard them (filter reject)
    output reg         desc_push,
    output wire [8:0]  desc_len,
    output wire [4:0]  desc_flags,
    output reg         ev_sync,
    output reg         ev_end,           // rx_end, one cycle before desc_push
    output reg         ev_done_ok,
    output reg         ev_done_bad,
    output reg         ev_overflow,
    input  wire        ack_pending,      // flag ACK_SENT in the descriptor

    // configuration
    input  wire [31:0] cfg_access_addr,
    input  wire [47:0] cfg_own_addr,
    input  wire        cfg_own_addr_type,
    input  wire [15:0] cfg_pan_id,
    input  wire [15:0] cfg_short_addr,
    input  wire [63:0] cfg_ext_addr,
    input  wire        cfg_promiscuous,

    // lower-MAC view of the finished packet (valid with ev_end)
    output wire        fcs_ok,
    output wire        accept,
    output wire        ack_eligible,
    output wire        is_ack,
    output wire        ack_req,
    output wire [7:0]  seq
);
    // ---- per-packet state ------------------------------------------------
    reg [2:0]  bitc;
    reg [7:0]  shreg;
    reg [8:0]  oct_idx;         // octets received so far (incoming side)
    reg [8:0]  pushed;          // octets accepted into the FIFO
    reg [7:0]  len_le;          // LE: length octet (header octet 1)
    reg [7:0]  hdr0;            // LE: header octet 0
    reg [47:0] adv_a;
    reg [15:0] fc;              // 15.4 frame control
    reg [7:0]  seq_r;
    reg [15:0] dpan;
    reg [63:0] daddr;
    reg [7:0]  d1, d2;          // 15.4 delay line (octet n-1, n-2)
    reg        crc_seen, trunc, ign, got_sync;

    wire le_bit = ev_valid && (ev_kind == 4'd1) && !phy;
    wire oq_oct = ev_valid && (ev_kind == 4'd7) && phy;
    wire crc_ev = ev_valid && (ev_kind == 4'd5);
    wire sync_ev = ev_valid && (ev_kind == 4'd2);

    wire       le_oct_v = le_bit && (bitc == 3'd7);
    wire [7:0] le_oct   = {ev_value[0], shreg[7:1]};
    wire       oct_v    = le_oct_v | oq_oct;
    wire [7:0] oct      = phy ? ev_value[7:0] : le_oct;

    // LE keeps header + payload (2 + length octets), drops the CRC bits
    wire [9:0] le_total = 10'd2 + {2'b00, len_le};
    wire       le_keep  = (oct_idx < 9'd2) || ({1'b0, oct_idx} < le_total);

    // FIFO push of this event
    wire       oq_keep  = (oct_idx >= 9'd2);
    wire       want     = !ign && oct_v && (phy ? oq_keep : le_keep);
    wire [7:0] wd       = phy ? d2 : oct;

    // a CRC-good packet the filter rejects is dropped; both strobes are valid with ev_end
    wire rejected = fcs_ok && !accept;
    assign rx_rollback = ev_end && rejected;
    assign rx_commit   = ev_end && !rejected;

    always @(posedge clk) begin
        rx_push     <= 1'b0;
        desc_push   <= 1'b0;
        ev_sync     <= 1'b0;
        ev_end      <= 1'b0;
        ev_done_ok  <= 1'b0;
        ev_done_bad <= 1'b0;
        ev_overflow <= 1'b0;
        if (!rst_n) begin
            bitc <= 3'd0; shreg <= 8'd0; oct_idx <= 9'd0; pushed <= 9'd0;
            len_le <= 8'd0; hdr0 <= 8'd0; adv_a <= 48'd0; fc <= 16'd0; seq_r <= 8'd0;
            dpan <= 16'd0; daddr <= 64'd0; d1 <= 8'd0; d2 <= 8'd0;
            crc_seen <= 1'b0; trunc <= 1'b0; ign <= 1'b0; got_sync <= 1'b0;
            rx_wdata <= 8'd0;
        end else begin
            if (sync_ev && !got_sync) begin
                got_sync <= 1'b1;
                ev_sync  <= 1'b1;
                if (desc_full) begin        // "packet ignored from the start"
                    ign         <= 1'b1;
                    ev_overflow <= 1'b1;
                end
            end
            if (crc_ev) crc_seen <= 1'b1;

            if (le_bit) begin
                shreg <= {ev_value[0], shreg[7:1]};
                bitc  <= bitc + 3'd1;
            end

            if (oct_v) begin
                oct_idx <= oct_idx + 9'd1;
                d1 <= oct;
                d2 <= d1;
                if (!phy) begin
                    if (oct_idx == 9'd0) hdr0   <= oct;
                    if (oct_idx == 9'd1) len_le <= oct;
                    if (oct_idx >= 9'd8 && oct_idx < 9'd14)
                        adv_a[{oct_idx[2:0], 3'b000} +: 8] <= oct;     // octets 8..13 -> bytes 0..5
                end else begin
                    if (oct_idx == 9'd0) fc[7:0]  <= oct;
                    if (oct_idx == 9'd1) fc[15:8] <= oct;
                    if (oct_idx == 9'd2) seq_r    <= oct;
                    if (oct_idx == 9'd3) dpan[7:0]  <= oct;
                    if (oct_idx == 9'd4) dpan[15:8] <= oct;
                    if (oct_idx >= 9'd5 && oct_idx < 9'd13) daddr[{oct_idx[2:0] - 3'd5, 3'b000} +: 8] <= oct;
                end
            end

            if (want) begin
                rx_push  <= 1'b1;
                rx_wdata <= wd;
                if (rx_full) trunc <= 1'b1;
                else         pushed <= pushed + 9'd1;
            end

            // end of packet: ev_end now, descriptor and done events one cycle later
            if (pkt_done) ev_end <= 1'b1;
            if (ev_end && !ign) begin
                desc_push   <= !rejected;
                ev_done_ok  <= fcs_ok && accept;
                ev_done_bad <= !(fcs_ok && accept);
            end
        end
    end

    // flags: [0] crc_ok [1] truncated [2] addr_match [3] ack_sent [4] phy
    assign fcs_ok     = pkt_crc_ok && crc_seen && !trunc && !ign;
    assign desc_len   = pushed;
    assign desc_flags = {phy, ack_pending, accept, trunc | !crc_seen, fcs_ok};

    // ---- filters ----------------------------------------------------------
    wire le_aa_match, le_checked, le_addr_match, le_accept;
    mac_le_filter u_lef (
        .own_aa(cfg_access_addr), .own_addr(cfg_own_addr), .own_addr_type(cfg_own_addr_type),
        .rx_aa(cfg_access_addr), .pdu_type(hdr0[3:0]), .rx_rxadd(hdr0[7]), .adv_a(adv_a),
        .aa_match(le_aa_match), .addr_checked(le_checked), .addr_match(le_addr_match),
        .accept(le_accept));

    wire f_accept, f_unicast, f_bcast, f_nodest, f_ack_el;
    mac_addr_filter_154 u_f154 (
        .promiscuous(cfg_promiscuous), .own_pan(cfg_pan_id), .own_short(cfg_short_addr),
        .own_ext(cfg_ext_addr), .dest_mode(fc[11:10]), .dest_pan(dpan), .dest_addr(daddr),
        .accept(f_accept), .unicast_me(f_unicast), .bcast(f_bcast), .no_dest(f_nodest),
        .ack_eligible(f_ack_el));

    assign accept       = phy ? f_accept : le_accept;
    assign ack_eligible = phy && f_ack_el;
    assign is_ack       = phy && (fc[2:0] == 3'd2);
    assign ack_req      = fc[5];
    assign seq          = seq_r;

    wire _unused = &{1'b0, shreg[0], hdr0[6:4], fc[15:12], fc[9:6], fc[4:3], le_aa_match, le_checked, le_addr_match, f_unicast, f_bcast, f_nodest,
                     ev_value[23:8]};
endmodule
