// Timestamp counter and event capture (spec/host-interface.md sec. 4).
// 32-bit tick (1 us) plus 5-bit sub-tick counting core cycles inside the tick.
// CLK_PER_US is 32 at 32 MHz, 16 at the 16 MHz fallback (1..32).
// Reading TS_SUB (the low word) latches the tick into tick_latched for TS_TICK.
// Captures hold {tick, sub} as of the cycle in which the event strobe is high.
module host_timestamp #(
    parameter CLK_PER_US = 32
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rd_sub,         // TS_SUB (low word) is being read: latch tick
    output reg  [31:0] tick,
    output reg  [4:0]  sub,
    output reg  [31:0] tick_latched,
    input  wire        ev_rx_sync,
    input  wire        ev_rx_end,
    input  wire        ev_tx_start,
    input  wire        ev_tx_end,
    input  wire        ev_trigger,
    output reg  [36:0] cap_rx_start,
    output reg  [36:0] cap_rx_end,
    output reg  [36:0] cap_tx_start,
    output reg  [36:0] cap_tx_end,
    output reg  [36:0] cap_trigger
);
    localparam [31:0] LAST32 = CLK_PER_US - 1;
    localparam [4:0]  LAST   = LAST32[4:0];

    wire [36:0] now = {tick, sub};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tick         <= 32'd0;
            sub          <= 5'd0;
            tick_latched <= 32'd0;
            cap_rx_start <= 37'd0;
            cap_rx_end   <= 37'd0;
            cap_tx_start <= 37'd0;
            cap_tx_end   <= 37'd0;
            cap_trigger  <= 37'd0;
        end else begin
            if (sub == LAST) begin
                sub  <= 5'd0;
                tick <= tick + 32'd1;
            end else begin
                sub <= sub + 5'd1;
            end
            if (rd_sub)      tick_latched <= tick;
            if (ev_rx_sync)  cap_rx_start <= now;
            if (ev_rx_end)   cap_rx_end   <= now;
            if (ev_tx_start) cap_tx_start <= now;
            if (ev_tx_end)   cap_tx_end   <= now;
            if (ev_trigger)  cap_trigger  <= now;
        end
    end
endmodule
