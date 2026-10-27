// LE own-address and access-address compare (decision 0006 row 14).
// Combinational; inputs held stable until `rx_end`.
//
// `aa_match`: received AA equals the configured AA (advertising AA or the
// connection AA). For SCAN_REQ and CONNECT_IND the AdvA field must equal the
// own address and the RxAdd header bit must equal the own address type;
// other PDU types are not address-checked here. The accept list and resolving
// list are software (row 15).
module mac_le_filter (
    input  wire [31:0] own_aa,
    input  wire [47:0] own_addr,
    input  wire        own_addr_type,   // 0 public, 1 random
    input  wire [31:0] rx_aa,
    input  wire [3:0]  pdu_type,        // advertising PDU header type
    input  wire        rx_rxadd,        // RxAdd header bit
    input  wire [47:0] adv_a,           // AdvA field of SCAN_REQ / CONNECT_IND
    output wire        aa_match,
    output wire        addr_checked,
    output wire        addr_match,
    output wire        accept
);
    localparam [3:0] PDU_SCAN_REQ    = 4'h3;
    localparam [3:0] PDU_CONNECT_IND = 4'h5;

    assign aa_match     = (rx_aa == own_aa);
    assign addr_checked = (pdu_type == PDU_SCAN_REQ) | (pdu_type == PDU_CONNECT_IND);
    assign addr_match   = (adv_a == own_addr) & (rx_rxadd == own_addr_type);
    assign accept       = aa_match & (~addr_checked | addr_match);
endmodule
