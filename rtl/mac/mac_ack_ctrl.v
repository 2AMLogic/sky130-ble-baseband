// 15.4 automatic acknowledgement controller (decision 0006 row 11, R3).
//
// On `rx_end` (end-of-packet decision cycle, after L_rx) a received frame
// earns an ACK when ACK is enabled, the FCS passed, the frame requested an
// ACK, it is not itself an ACK, and the address filter says it is a unicast
// to this device (`rx_ack_eligible`, see mac_addr_filter_154). The ACK start
// command `ack_tx_req` (one-cycle strobe, host event ACK_SENT) is issued
// TURNAROUND_CYCLES - L_DIG_CYCLES cycles later: the air-interface deadline
// (end of received frame to ACK SHR, 192 us = 6144 cycles at 32 MHz) minus
// the digital latency L_dig of timing-and-area section 3 (L_rx + L_tx;
// 1024 cycles at 32 MHz, 15.4). L_DIG_CYCLES must equal the real
// L_rx + L_tx of the integrated design (#52), or the ACK moves off the deadline.
//
// The sequence number and frame-pending bit are frozen at `rx_end`
// (`ack_seq`, `ack_fp`); frame-pending comes from a host register (R3).
// A pending ACK is cancelled by `abort_req`, by `ack_enable` clearing, or by a
// later `rx_end` that does not itself qualify. A later qualifying `rx_end`
// restarts the turnaround for the newer frame.
module mac_ack_ctrl #(
    parameter integer TURNAROUND_CYCLES = 6144,   // 3072 at 16 MHz
    parameter integer L_DIG_CYCLES      = 1024    // 512 at 16 MHz
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ack_enable,
    input  wire       fp_bit,
    input  wire       rx_end,
    input  wire       rx_fcs_ok,
    input  wire       rx_ack_req,
    input  wire       rx_is_ack,
    input  wire       rx_ack_eligible,
    input  wire [7:0] rx_seq,
    input  wire       abort_req,
    output wire       ack_tx_req,
    output reg  [7:0] ack_seq,
    output reg        ack_fp,
    output wire       ack_pending
);
    wire eligible = rx_end & ack_enable & rx_fcs_ok & rx_ack_req
                  & ~rx_is_ack & rx_ack_eligible;

    mac_timer #(.CYCLES(TURNAROUND_CYCLES - L_DIG_CYCLES)) u_turn (
        .clk(clk), .rst_n(rst_n),
        .start(eligible),
        .cancel(abort_req | ~ack_enable | (rx_end & ~eligible)),
        .busy(ack_pending),
        .fire(ack_tx_req)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            ack_seq <= 8'd0;
            ack_fp  <= 1'b0;
        end else if (eligible) begin
            ack_seq <= rx_seq;
            ack_fp  <= fp_bit;
        end
    end
endmodule
