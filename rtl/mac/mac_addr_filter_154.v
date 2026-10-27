// 15.4 address filter (decision 0006 row 13). Combinational; the receive
// framing holds the parsed destination fields stable until `rx_end`.
//
// dest_mode: 2'b00 none, 2'b10 short (dest_addr[15:0]), 2'b11 extended
// (dest_addr[63:0]), 2'b01 reserved (rejected). dest_pan is the resolved
// destination PAN (meaningful when dest_mode != 0).
//
// Rules implemented (spec clauses unverified, see 0006 citation status):
//   - PAN passes if it equals own_pan or is the broadcast PAN 0xFFFF.
//   - Short address passes if it equals own_short; own_short 0xFFFE
//     (no short address assigned) and 0xFFFF never match as unicast.
//   - Short address 0xFFFF with a passing PAN is broadcast.
//   - Extended address passes if it equals own_ext.
//   - No destination address (mode 0): accepted, flagged `no_dest`; whether it
//     is for this device (PAN-coordinator rules) is software's call.
//   - Promiscuous: everything accepted; no automatic ACK in this mode
//     (project assumption, to be checked against the clause).
module mac_addr_filter_154 (
    input  wire        promiscuous,
    input  wire [15:0] own_pan,
    input  wire [15:0] own_short,
    input  wire [63:0] own_ext,
    input  wire [1:0]  dest_mode,
    input  wire [15:0] dest_pan,
    input  wire [63:0] dest_addr,
    output wire        accept,
    output wire        unicast_me,
    output wire        bcast,
    output wire        no_dest,
    output wire        ack_eligible
);
    wire mode_short = (dest_mode == 2'b10);
    wire mode_ext   = (dest_mode == 2'b11);
    wire pan_ok     = (dest_pan == own_pan) | (dest_pan == 16'hFFFF);
    wire short_bc   = mode_short & (dest_addr[15:0] == 16'hFFFF);
    wire short_hit  = mode_short & (dest_addr[15:0] == own_short)
                    & (own_short != 16'hFFFF) & (own_short != 16'hFFFE);
    wire ext_hit    = mode_ext & (dest_addr == own_ext);

    assign unicast_me   = pan_ok & (short_hit | ext_hit);
    assign bcast        = pan_ok & short_bc;
    assign no_dest      = (dest_mode == 2'b00);
    assign accept       = promiscuous | unicast_me | bcast | no_dest;
    assign ack_eligible = unicast_me & ~promiscuous;
endmodule
