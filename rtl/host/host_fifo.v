// Synchronous octet FIFO, first-word-fall-through (host interface, spec/host-interface.md sec. 2).
// A push while full is refused (older data is never overwritten) and reported on
// `overflow`; a pop while empty returns 0 and is reported on `underflow`. Both are
// same-cycle strobes. `flush` empties the FIFO and wins over push/pop in that cycle.
// DEPTH must be 1..511 (level is 9 bits).
//
// HOLD = 1 makes pushed octets provisional (the RX FIFO): they take space and count
// toward `full`, but the read side (`level`, `empty`, `rdata`, pop) only sees octets
// already committed. `commit` publishes every provisional octet; `rollback` discards
// them, restoring the write pointer to where the packet began. Rollback wins over
// commit, and also discards a push in the same cycle. HOLD = 0 (the TX FIFO)
// commits every push at once and ignores both inputs.
module host_fifo #(
    parameter DEPTH = 288,
    parameter HOLD  = 0
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       flush,
    input  wire       push,
    input  wire [7:0] wdata,
    input  wire       pop,
    input  wire       commit,
    input  wire       rollback,
    output wire [7:0] rdata,
    output wire [8:0] level,
    output wire       full,
    output wire       empty,
    output wire       overflow,
    output wire       underflow
);
    localparam [31:0] LAST32 = DEPTH - 1;
    localparam [8:0]  LAST   = LAST32[8:0];
    localparam [31:0] DEPTH32 = DEPTH;
    localparam [8:0]  DEPTH_W = DEPTH32[8:0];

    reg [7:0] mem[0:DEPTH-1];
    reg [8:0] rp, wp, cnt;      // cnt: octets stored, provisional ones included
    reg [8:0] unc;              // provisional octets (always 0 when HOLD = 0)

    wire [8:0] vis = cnt - unc; // octets the read side may see
    wire [8:0] wp_back = (wp >= unc) ? (wp - unc) : (wp + DEPTH_W - unc);

    assign full      = (cnt == DEPTH_W);
    assign empty     = (vis == 9'd0);
    assign level     = vis;
    assign overflow  = push & full;
    assign underflow = pop & empty;
    assign rdata     = empty ? 8'h00 : mem[rp];

    wire do_push = push & ~full;
    wire do_pop  = pop & ~empty;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rp  <= 9'd0;
            wp  <= 9'd0;
            cnt <= 9'd0;
            unc <= 9'd0;
        end else if (flush) begin
            rp  <= 9'd0;
            wp  <= 9'd0;
            cnt <= 9'd0;
            unc <= 9'd0;
        end else if (HOLD != 0 && rollback) begin
            wp  <= wp_back;
            cnt <= vis - (do_pop ? 9'd1 : 9'd0);
            unc <= 9'd0;
            if (do_pop) rp <= (rp == LAST) ? 9'd0 : rp + 9'd1;
        end else begin
            if (HOLD != 0) begin
                if (commit) unc <= 9'd0;
                else if (do_push) unc <= unc + 9'd1;
            end
            if (do_push) begin
                mem[wp] <= wdata;
                wp      <= (wp == LAST) ? 9'd0 : wp + 9'd1;
            end
            if (do_pop) rp <= (rp == LAST) ? 9'd0 : rp + 9'd1;
            if (do_push & ~do_pop) cnt <= cnt + 9'd1;
            else if (~do_push & do_pop) cnt <= cnt - 9'd1;
        end
    end
endmodule
