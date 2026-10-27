// LE 1M packet framing: produces the on-air bit sequence one bit per
// `bit_req`, in the order of frame() in sim/model/le1m_tx.py:
//   preamble (8 bits, 0x55 if access_address[0] else 0xAA, LSB first),
//   access address (32 bits, LSB first),
//   PDU octets (LSB first) then the 24 CRC bits (MSB of the register first),
//   the last two groups whitened.
// PDU octets are pulled through a one-deep ready/valid prefetch so the host
// side needs no buffer for a whole PDU; `pdu_len` octets (0..257) are requested.
module le1m_frame (
    input  wire        clk,
    input  wire        rst_n,           // active-low synchronous reset
    input  wire        load,            // start a packet; latches the parameters below
    input  wire [31:0] access_address,
    input  wire [5:0]  channel,         // whitening channel index 0..39
    input  wire [23:0] crc_init,
    input  wire [8:0]  pdu_len,         // PDU length in octets, 0..257 (not checked)
    output wire        pdu_ready,       // wants the next PDU octet
    input  wire        pdu_valid,
    input  wire [7:0]  pdu_data,
    input  wire        bit_req,         // consume the next on-air bit this cycle
    output wire        bit_out,         // that bit (combinational, valid with bit_req)
    output wire        bit_last,        // that bit is the final CRC bit
    output reg         underrun         // sticky: an octet was needed before it arrived
);
    localparam [1:0] K_PRE = 2'd0, K_AA = 2'd1, K_PDU = 2'd2, K_CRC = 2'd3;

    reg [1:0]  kind;
    reg [4:0]  cnt;       // bit index within preamble / access address / CRC
    reg [2:0]  bitpos;    // bit index within the current PDU octet
    reg [8:0]  oct_left;  // PDU octets not yet fully emitted
    reg [8:0]  req_cnt;   // PDU octets already requested from the host
    reg [8:0]  len;
    reg [31:0] aa;
    reg [7:0]  cur;       // remaining bits of the octet being emitted
    reg [7:0]  nxt;       // prefetched octet
    reg        nxt_full;
    reg        run;

    wire pdu_phase = (kind == K_PDU);
    wire crc_phase = (kind == K_CRC);
    wire [7:0] src = (bitpos == 3'd0) ? nxt : cur;
    wire d = src[0];
    wire crc_msb;
    wire wh_out;
    wire take = bit_req & run;

    le1m_whiten u_whiten (
        .clk(clk), .rst_n(rst_n), .load(load), .channel(channel),
        .en(take & (pdu_phase | crc_phase)),
        .din(pdu_phase ? d : crc_msb), .dout(wh_out)
    );

    le1m_crc24 u_crc (
        .clk(clk), .rst_n(rst_n), .load(load), .init(crc_init),
        .upd(take & pdu_phase), .din(d),
        .shift(take & crc_phase), .msb(crc_msb)
    );

    assign pdu_ready = run & ~nxt_full & (req_cnt != len);
    assign bit_out   = (kind == K_PRE) ? (aa[0] ^ cnt[0]) :
                       (kind == K_AA)  ? aa[cnt] : wh_out;
    assign bit_last  = crc_phase & (cnt == 5'd23);

    always @(posedge clk) begin
        if (!rst_n) begin
            run      <= 1'b0;
            kind     <= K_PRE;
            cnt      <= 5'd0;
            bitpos   <= 3'd0;
            oct_left <= 9'd0;
            req_cnt  <= 9'd0;
            len      <= 9'd0;
            aa       <= 32'd0;
            cur      <= 8'd0;
            nxt      <= 8'd0;
            nxt_full <= 1'b0;
            underrun <= 1'b0;
        end else if (load) begin
            run      <= 1'b1;
            kind     <= K_PRE;
            cnt      <= 5'd0;
            bitpos   <= 3'd0;
            oct_left <= pdu_len;
            req_cnt  <= 9'd0;
            len      <= pdu_len;
            aa       <= access_address;
            nxt_full <= 1'b0;
            underrun <= 1'b0;
        end else begin
            if (take) begin
                case (kind)
                    K_PRE: begin
                        cnt <= cnt + 5'd1;
                        if (cnt == 5'd7) begin
                            kind <= K_AA;
                            cnt  <= 5'd0;
                        end
                    end
                    K_AA: begin
                        cnt <= cnt + 5'd1;
                        if (cnt == 5'd31) begin
                            cnt  <= 5'd0;
                            kind <= (len == 9'd0) ? K_CRC : K_PDU;
                        end
                    end
                    K_PDU: begin
                        cur    <= {1'b0, src[7:1]};
                        bitpos <= bitpos + 3'd1;
                        if (bitpos == 3'd0) begin
                            nxt_full <= 1'b0;
                            if (!nxt_full) underrun <= 1'b1;
                        end
                        if (bitpos == 3'd7) begin
                            oct_left <= oct_left - 9'd1;
                            if (oct_left == 9'd1) begin
                                kind <= K_CRC;
                                cnt  <= 5'd0;
                            end
                        end
                    end
                    default: begin  // K_CRC
                        cnt <= cnt + 5'd1;
                        if (cnt == 5'd23) run <= 1'b0;
                    end
                endcase
            end
            if (pdu_valid & pdu_ready) begin
                nxt      <= pdu_data;
                nxt_full <= 1'b1;
                req_cnt  <= req_cnt + 9'd1;
            end
        end
    end
endmodule
