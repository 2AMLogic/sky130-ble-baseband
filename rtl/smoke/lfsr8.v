// PLACEHOLDER -- NOT PART OF THE BASEBAND DESIGN.
//
// 8-bit Fibonacci LFSR (x^8 + x^6 + x^5 + x^4 + 1, maximal length, period
// 255), used only to prove the flow end to end: cocotb + Icarus simulation,
// lint with Verilator, and Yosys synthesis to sky130_fd_sc_hd. Delete it once
// real RTL exercises the same flow. It sets no clock, area or interface target.
module lfsr8 (
    input  wire       clk,
    input  wire       rst_n,  // active-low synchronous reset, loads 8'h01
    input  wire       en,
    output wire [7:0] q
);
    reg [7:0] state;

    always @(posedge clk) begin
        if (!rst_n)
            state <= 8'h01;
        else if (en)
            state <= {state[6:0], state[7] ^ state[5] ^ state[4] ^ state[3]};
    end

    assign q = state;
endmodule
