// Interval timer core for the lower MAC (decision 0006 rows 8, 9, 11).
//
// Instantiated for LE T_IFS, 15.4 turnaround and 15.4 ACK-wait. A one-cycle
// `start` strobe sampled on clock edge S makes `fire` (one-cycle strobe) first
// visible after edge S + CYCLES. Counts are cycles of `clk`; the wall-clock
// meaning depends on the clock frequency (32 MHz target, 16 MHz fallback).
//
// Priority on a single edge: cancel > start > count.
//   - cancel suppresses a fire that would have been produced on that edge.
//   - start while running reloads the full count; if the old count expires on
//     that same edge, that expiry still fires and the timer runs again.
// Synchronous active-low reset.
module mac_timer #(
    parameter integer CYCLES = 4          // >= 1
) (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire cancel,
    output reg  busy,
    output reg  fire
);
    localparam integer W = (CYCLES > 1) ? $clog2(CYCLES + 1) : 1;

    reg [W-1:0] cnt;

    always @(posedge clk) begin
        fire <= 1'b0;
        if (!rst_n) begin
            busy <= 1'b0;
            cnt  <= {W{1'b0}};
        end else if (cancel) begin
            busy <= 1'b0;
        end else begin
            if (busy) begin
                cnt <= cnt - 1'b1;
                if (cnt == {{(W-1){1'b0}}, 1'b1}) begin
                    fire <= 1'b1;
                    busy <= 1'b0;
                end
            end
            if (start) begin
                busy <= 1'b1;
                cnt  <= CYCLES[W-1:0];
            end
        end
    end
endmodule
