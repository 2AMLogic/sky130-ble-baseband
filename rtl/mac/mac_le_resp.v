// LE T_IFS timer and timed-response trigger (decision 0006 rows 8, 12, R1).
//
// 150 us = 4800 cycles at 32 MHz (2400 at 16 MHz), +/- 64 cycles at 32 MHz.
// The command fires TIFS_CYCLES - L_DIG_CYCLES cycles after the end-of-packet
// decision (timing-and-area section 3, LE: L_dig <= 320 cycles at 32 MHz), so
// the first transmitted bit lands on T_IFS at the air interface.
//
// Received-packet path: `rx_end` starts the timer only if the response is
// enabled, the AA/address filter accepted the packet (`rx_accept`, see
// mac_le_filter) and the CRC passed (or CRC gating is configured off, R1).
// `resp_tx_req` (one-cycle strobe, host event RESPONSE_SENT) transmits the
// pre-loaded packet; SN/NESN patching is not done here (open item in 0008).
// Own-packet path: `tx_end` starts the same interval, ungated, and the result
// is `ifs_after_tx` (T_IFS after our own transmission, e.g. to open RX).
// A non-qualifying `rx_end`, `abort_req` or `resp_enable` clearing cancels a
// pending received-packet response.
module mac_le_resp #(
    parameter integer TIFS_CYCLES  = 4800,
    parameter integer L_DIG_CYCLES = 320
) (
    input  wire clk,
    input  wire rst_n,
    input  wire resp_enable,
    input  wire crc_gate_en,
    input  wire rx_end,
    input  wire rx_crc_ok,
    input  wire rx_accept,
    input  wire tx_end,
    input  wire abort_req,
    output wire resp_tx_req,
    output wire ifs_after_tx,
    output wire ifs_busy
);
    wire go_rx = rx_end & resp_enable & rx_accept & (rx_crc_ok | ~crc_gate_en);
    wire fire;
    reg  src_tx;

    mac_timer #(.CYCLES(TIFS_CYCLES - L_DIG_CYCLES)) u_ifs (
        .clk(clk), .rst_n(rst_n),
        .start(go_rx | tx_end),
        .cancel(abort_req | (rx_end & ~go_rx) | (~src_tx & ifs_busy & ~resp_enable)),
        .busy(ifs_busy),
        .fire(fire)
    );

    always @(posedge clk) begin
        if (!rst_n)
            src_tx <= 1'b0;
        else if (go_rx | tx_end)
            src_tx <= tx_end;
    end

    assign resp_tx_req  = fire & ~src_tx;
    assign ifs_after_tx = fire &  src_tx;
endmodule
