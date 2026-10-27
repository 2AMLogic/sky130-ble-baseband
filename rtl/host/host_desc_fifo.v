// 4-entry RX packet-descriptor FIFO, first-word-fall-through (spec/host-interface.md sec. 2).
// Entry layout is opaque here (W bits); host_top packs and unpacks it. A push while
// four are held is dropped and reported on `overflow`. Head reads 0 when empty.
module host_desc_fifo #(
    parameter W = 96
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         flush,
    input  wire         push,
    input  wire [W-1:0] wdata,
    input  wire         pop,
    output wire [W-1:0] head,
    output wire [2:0]   count,
    output wire         full,
    output wire         empty,
    output wire         overflow
);
    reg [W-1:0] mem[0:3];
    reg [1:0]   rp, wp;
    reg [2:0]   cnt;

    assign full     = (cnt == 3'd4);
    assign empty    = (cnt == 3'd0);
    assign count    = cnt;
    assign overflow = push & full;
    assign head     = empty ? {W{1'b0}} : mem[rp];

    wire do_push = push & ~full;
    wire do_pop  = pop & ~empty;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rp  <= 2'd0;
            wp  <= 2'd0;
            cnt <= 3'd0;
        end else if (flush) begin
            rp  <= 2'd0;
            wp  <= 2'd0;
            cnt <= 3'd0;
        end else begin
            if (do_push) begin
                mem[wp] <= wdata;
                wp      <= wp + 2'd1;
            end
            if (do_pop) rp <= rp + 2'd1;
            if (do_push & ~do_pop) cnt <= cnt + 3'd1;
            else if (~do_push & do_pop) cnt <= cnt - 3'd1;
        end
    end
endmodule
