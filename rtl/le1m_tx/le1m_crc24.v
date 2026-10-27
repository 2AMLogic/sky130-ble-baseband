// LE 1M CRC-24, polynomial 0x00065B (Core Specification Vol 6 Part B 3.1.1).
// Bit-exact with crc24() and crc_bits() in sim/model/le1m_tx.py. `upd`
// folds one PDU bit into the register; `shift` then presents the register
// MSB first (register bit 23 is sent first) while moving it left.
module le1m_crc24 (
    input  wire        clk,
    input  wire        rst_n,  // active-low synchronous reset
    input  wire        load,   // preset the register from `init`
    input  wire [23:0] init,
    input  wire        upd,    // fold `din` into the register
    input  wire        din,
    input  wire        shift,  // emit one CRC bit: msb is valid this cycle
    output wire        msb
);
    reg [23:0] state;

    always @(posedge clk) begin
        if (!rst_n)
            state <= 24'h555555;
        else if (load)
            state <= init;
        else if (upd)
            state <= {state[22:0], 1'b0} ^ ((state[23] ^ din) ? 24'h00065B : 24'h000000);
        else if (shift)
            state <= {state[22:0], 1'b0};
    end

    assign msb = state[23];
endmodule
