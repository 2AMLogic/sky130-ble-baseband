// Timestamp counter and compare trigger (decision 0006 row 10,
// spec/host-interface.md section 4).
//
// Counter: `ts_tick` counts microseconds (CLK_PER_US core cycles per tick,
// 32 at 32 MHz, 16 at 16 MHz), `ts_sub` counts core cycles inside the tick.
// Both are zero in the first cycle after reset release.
//
// Trigger: `trig_arm` (one-cycle strobe) latches `trig_cmp` and the TX/RX
// selection. The trigger fires when the counter equals the compare value at
// sub-tick 0, so its resolution is 1 us, and the fire time is a fixed number
// of cycles after that instant (jitter 0 cycles in this block; spec allows 1).
// Arm at least one tick ahead: a compare value already in the past does not
// fire until the 32-bit tick wraps (about 71.6 minutes). A fire disarms.
// `trig_cancel` disarms and wins over `trig_arm` on the same edge.
module mac_trigger #(
    parameter integer CLK_PER_US = 32     // 2..32 (sub-tick field is 5 bits)
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        trig_arm,
    input  wire        trig_cancel,
    input  wire [31:0] trig_cmp,
    input  wire        trig_mode_tx,      // sampled at arm: 1 = start TX, 0 = start RX
    output reg  [31:0] ts_tick,
    output reg  [4:0]  ts_sub,
    output reg         trig_armed,
    output reg         trig_fire,         // strobe, any mode (event TRIGGER)
    output wire        trig_start_tx,     // strobe
    output wire        trig_start_rx      // strobe
);
    reg [31:0] cmp_q;
    reg        mode_tx_q;
    reg        fire_tx, fire_rx;

    assign trig_start_tx = fire_tx;
    assign trig_start_rx = fire_rx;

    always @(posedge clk) begin
        trig_fire <= 1'b0;
        fire_tx   <= 1'b0;
        fire_rx   <= 1'b0;
        if (!rst_n) begin
            ts_tick    <= 32'd0;
            ts_sub     <= 5'd0;
            trig_armed <= 1'b0;
            cmp_q      <= 32'd0;
            mode_tx_q  <= 1'b0;
        end else begin
            if (ts_sub == 5'(CLK_PER_US - 1)) begin
                ts_sub  <= 5'd0;
                ts_tick <= ts_tick + 32'd1;
            end else begin
                ts_sub  <= ts_sub + 5'd1;
            end

            if (trig_armed && ts_tick == cmp_q && ts_sub == 5'd0) begin
                trig_armed <= 1'b0;
                trig_fire  <= 1'b1;
                fire_tx    <= mode_tx_q;
                fire_rx    <= ~mode_tx_q;
            end
            if (trig_arm) begin
                trig_armed <= 1'b1;
                cmp_q      <= trig_cmp;
                mode_tx_q  <= trig_mode_tx;
            end
            if (trig_cancel)
                trig_armed <= 1'b0;
        end
    end
endmodule
