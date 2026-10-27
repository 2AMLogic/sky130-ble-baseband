// Synchronous octet FIFO, first-word-fall-through (host interface, spec/host-interface.md sec. 2).
// A push while full is refused (older data is never overwritten) and reported on
// `overflow`; a pop while empty returns 0 and is reported on `underflow`. Both are
// same-cycle strobes. `flush` empties the FIFO and wins over push/pop in that cycle.
// DEPTH must be 1..511 (level is 9 bits).
module host_fifo #(
    parameter DEPTH = 288
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       flush,
    input  wire       push,
    input  wire [7:0] wdata,
    input  wire       pop,
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
    reg [8:0] rp, wp, cnt;

    assign full      = (cnt == DEPTH_W);
    assign empty     = (cnt == 9'd0);
    assign level     = cnt;
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
        end else if (flush) begin
            rp  <= 9'd0;
            wp  <= 9'd0;
            cnt <= 9'd0;
        end else begin
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
