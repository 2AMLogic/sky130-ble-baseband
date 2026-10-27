// Mode and turnaround sequencer: STATE register, front-end mode control
// (spec/frontend-interface.md section 4), TX start check
// (spec/host-interface.md section 2 "TX start with fewer octets than TX_LENGTH").
//
// Sequence. A channel/PHY change is sent to the front end first (`fe_chan_we`).
// RX: fe_rx_en, wait for fe_ready, run the receiver until `rx_end`. TX: fe_tx_en,
// wait for fe_ready, then start the modulator when a TX request is pending. After
// an RX that earned a timed response (LE T_IFS, 15.4 ACK) the front end is
// switched to TX at rx_end, so the synthesizer settles inside the turnaround; the
// request from the MAC timer then finds fe_ready already high. After a TX that
// opened an ACK-wait or T_IFS window the front end goes back to RX.
// fe_ready is only trusted 3 clk after a change of fe_rx_en / fe_tx_en /
// fe_chan_we, because the front end has 2 clk to deassert it.
//
// STATE (state_i): 0 idle, 1 RX, 2 TX, 3 turnaround (waiting for fe_ready).
module bb_ctrl (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ctrl_enable,
    input  wire       ctrl_phy,
    input  wire [6:0] ctrl_chan,
    input  wire       cmd_tx_start,
    input  wire       cmd_rx_start,
    input  wire       cmd_abort,

    input  wire       fe_ready,
    output reg        fe_rx_en,
    output reg        fe_tx_en,
    output reg  [6:0] fe_chan,
    output reg        fe_chan_we,
    output reg        fe_phy,

    // lower MAC
    input  wire       resp_tx_req,      // LE timed response
    input  wire       ack_tx_req,       // 15.4 automatic ACK
    input  wire       trig_start_tx,
    input  wire       trig_start_rx,
    input  wire       resp_pending,     // a timed response is scheduled after rx_end
    input  wire       after_tx_rx,      // an RX window follows the TX that just ended

    // datapath
    input  wire       rx_end,
    input  wire       tx_fin,
    input  wire [8:0] tx_length,
    input  wire [8:0] tx_level,
    output wire       rx_run,
    output reg        tx_begin,
    output reg        tx_ack_mode,
    output reg        tx_refused,       // start check failed or request while busy
    output reg        abort_o,
    output wire [2:0] state_i
);
    localparam [2:0] S_IDLE = 3'd0, S_RXW = 3'd1, S_RX = 3'd2, S_RXE = 3'd3,
                     S_TXW = 3'd4, S_TX = 3'd5, S_TXE = 3'd6;
    reg [2:0] st;
    reg [1:0] hold;
    reg [1:0] dwell;
    reg       pend_tx, pend_rx, pend_ack;
    reg       rx_q, tx_q;

    assign rx_run  = (st == S_RX);
    assign state_i = (st == S_RX || st == S_RXE) ? 3'd1 :
                     (st == S_TX || st == S_TXE) ? 3'd2 :
                     (st == S_IDLE) ? 3'd0 : 3'd3;

    wire dirty    = (ctrl_chan != fe_chan) || (ctrl_phy != fe_phy);
    wire rdy      = fe_ready && (hold == 2'd0) && !fe_chan_we;
    wire req_tx   = cmd_tx_start | trig_start_tx | resp_tx_req;
    wire in_cmd   = (st == S_IDLE) || (st == S_TXW);

    // TX start check: whole payload present and within the PHY's limit
    wire len_ok = fe_phy ? (tx_length <= 9'd125) : (tx_length <= 9'd257);
    wire ok_tx  = pend_ack || ((tx_level >= tx_length) && len_ok);

    always @(posedge clk) begin
        fe_chan_we <= 1'b0;
        tx_begin   <= 1'b0;
        tx_refused <= 1'b0;
        abort_o    <= 1'b0;
        rx_q <= fe_rx_en;
        tx_q <= fe_tx_en;
        if (!rst_n) begin
            st <= S_IDLE; hold <= 2'd0; dwell <= 2'd0;
            pend_tx <= 1'b0; pend_rx <= 1'b0; pend_ack <= 1'b0;
            fe_rx_en <= 1'b0; fe_tx_en <= 1'b0; fe_chan <= 7'd0; fe_phy <= 1'b0;
            tx_ack_mode <= 1'b0;
            rx_q <= 1'b0; tx_q <= 1'b0;
        end else begin
            if (fe_rx_en != rx_q || fe_tx_en != tx_q || fe_chan_we) hold <= 2'd3;
            else if (hold != 2'd0) hold <= hold - 2'd1;

            // requests
            if (ack_tx_req && in_cmd) begin pend_tx <= 1'b1; pend_ack <= 1'b1; end
            else if (req_tx) begin
                if (in_cmd && ctrl_enable) begin pend_tx <= 1'b1; pend_ack <= 1'b0; end
                else tx_refused <= 1'b1;
            end
            if ((cmd_rx_start | trig_start_rx) && st == S_IDLE && ctrl_enable) pend_rx <= 1'b1;

            case (st)
                S_IDLE: if (ctrl_enable) begin
                    if (dirty) begin
                        fe_chan <= ctrl_chan; fe_phy <= ctrl_phy; fe_chan_we <= 1'b1;
                    end else if (hold == 2'd0) begin
                        if (pend_tx || req_tx || ack_tx_req) begin
                            st <= S_TXW; fe_tx_en <= 1'b1; fe_rx_en <= 1'b0;
                        end else if (pend_rx || cmd_rx_start || trig_start_rx) begin
                            st <= S_RXW; fe_rx_en <= 1'b1; fe_tx_en <= 1'b0; pend_rx <= 1'b0;
                        end
                    end
                end
                S_RXW: if (rdy) st <= S_RX;
                S_RX: if (rx_end) begin st <= S_RXE; dwell <= 2'd2; end
                S_RXE: begin
                    if (dwell != 2'd0) dwell <= dwell - 2'd1;
                    else if (resp_pending) begin
                        st <= S_TXW; fe_tx_en <= 1'b1; fe_rx_en <= 1'b0;
                    end else begin
                        st <= S_IDLE; fe_rx_en <= 1'b0;
                    end
                end
                S_TXW: if (pend_tx && rdy) begin
                    pend_tx <= 1'b0; pend_ack <= 1'b0;
                    if (ok_tx) begin
                        tx_begin <= 1'b1; tx_ack_mode <= pend_ack; st <= S_TX;
                    end else begin
                        tx_refused <= 1'b1; st <= S_IDLE; fe_tx_en <= 1'b0;
                    end
                end
                S_TX: if (tx_fin) begin st <= S_TXE; dwell <= 2'd2; end
                S_TXE: begin
                    if (dwell != 2'd0) dwell <= dwell - 2'd1;
                    else if (after_tx_rx && ctrl_enable) begin
                        st <= S_RXW; fe_rx_en <= 1'b1; fe_tx_en <= 1'b0;
                    end else begin
                        st <= S_IDLE; fe_tx_en <= 1'b0;
                    end
                end
                default: st <= S_IDLE;
            endcase

            if (cmd_abort || !ctrl_enable) begin
                st <= S_IDLE; fe_rx_en <= 1'b0; fe_tx_en <= 1'b0;
                pend_tx <= 1'b0; pend_rx <= 1'b0; pend_ack <= 1'b0;
                abort_o <= cmd_abort || (st != S_IDLE);
            end
        end
    end
endmodule
