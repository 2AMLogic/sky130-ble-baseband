// 15.4 ACK-wait timer (decision 0006 row 9): macAckWaitDuration, 864 us =
// 27648 cycles at 32 MHz (13824 at 16 MHz).
//
// `tx_frame_end` with `tx_expect_ack` set (sampled on that edge) starts the
// wait. `ack_rx` while waiting cancels it (`ev_ack_received`, comb). Expiry
// raises `ev_ack_timeout` (one-cycle strobe, host event ACK_TIMEOUT), at or
// after the constant, never before. `ack_rx` on the same edge as expiry wins:
// no timeout. `abort_req` cancels silently. A new `tx_frame_end` restarts the wait.
module mac_ackwait #(
    parameter integer ACKWAIT_CYCLES = 27648
) (
    input  wire clk,
    input  wire rst_n,
    input  wire tx_frame_end,
    input  wire tx_expect_ack,
    input  wire ack_rx,
    input  wire abort_req,
    output wire ackwait_busy,
    output wire ev_ack_received,
    output wire ev_ack_timeout
);
    assign ev_ack_received = ack_rx & ackwait_busy;

    mac_timer #(.CYCLES(ACKWAIT_CYCLES)) u_wait (
        .clk(clk), .rst_n(rst_n),
        .start(tx_frame_end & tx_expect_ack),
        .cancel(ack_rx | abort_req),
        .busy(ackwait_busy),
        .fire(ev_ack_timeout)
    );
endmodule
