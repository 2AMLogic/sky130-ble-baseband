// LE 1M data whitening, x^7+x^4+1 (Core Specification Vol 6 Part B 3.2).
// Bit-exact with whiten() in sim/model/le1m_tx.py: the 7-bit register is
// preset to 0x40 | channel, the output is din ^ state[0], and on each enable
// the register shifts right and, if the bit shifted out was 1, XORs 0x44.
module le1m_whiten (
    input  wire       clk,
    input  wire       rst_n,    // active-low synchronous reset
    input  wire       load,     // preset the register from `channel`
    input  wire [5:0] channel,  // channel index 0..39
    input  wire       en,       // consume one bit: advance the register
    input  wire       din,
    output wire       dout      // din ^ state[0], valid in the cycle `en` is high
);
    reg [6:0] state;

    always @(posedge clk) begin
        if (!rst_n)
            state <= 7'h40;
        else if (load)
            state <= {1'b1, channel};
        else if (en)
            state <= {1'b0, state[6:1]} ^ (state[0] ? 7'h44 : 7'h00);
    end

    assign dout = din ^ state[0];
endmodule
