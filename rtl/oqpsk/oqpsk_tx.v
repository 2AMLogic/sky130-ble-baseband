// IEEE 802.15.4 2.4 GHz O-QPSK transmit path: PSDU octets in, tx_dev words out.
//
// Bit-exact with sim/model/oqpsk_tx.py (decisions 0005 and 0007): the same
// words, in the same order, compared by tx_valid strobe index, not by clock
// cycle. Front-end signals follow spec/frontend-interface.md section 3.2.
//
// Chain: PSDU payload -> FCS (ITU-T CRC-16, init 0, reflected 0x8408, sent
// little-endian) -> SHR (4 x 00, SFD A7) / PHR (7-bit length, reserved 0) /
// PSDU -> 4-bit symbols, low nibble first -> 32-chip spreading -> half-sine
// O-QPSK as the constant-envelope frequency word: in chip interval k the word
// is 64 * s_k (s_k in {-1, 0, +1}), four words per interval.
//
// Interface
//   tx_start/tx_len   one-cycle pulse; tx_len = payload octets WITHOUT the FCS
//                     (0..125, so the PSDU is at most 127). The block appends
//                     the FCS. A start while busy, or with tx_len > 125, is
//                     refused (tx_reject pulses, nothing is sent).
//   psdu_idx/psdu_data  payload octet read port. psdu_idx is the index of the
//                     octet the block wants next; psdu_data must carry that
//                     octet in the same cycle (asynchronous-read buffer). It
//                     is sampled once per octet, at an octet boundary.
//   tx_tick           sample-grid enable from the wrapper: one pulse per
//                     output word, nominally every 4 clk at 32 MHz (8 Msps),
//                     with the +/-1 clk jitter the interface allows. Each
//                     tick produces one word, so the block has no clock
//                     divider and works unchanged at 16 MHz (a tick every
//                     2 clk).
//   tx_valid/tx_dev   word strobe, one clk after the tick; tx_dev is 0 when
//                     tx_valid is low.
//   tx_active         high from the first word to the tick after the last
//                     word, i.e. low again at tick index len(words) + 1, the
//                     reading of the model (sim/model/README.md).
//   tx_done           one-cycle pulse when tx_active falls.
module oqpsk_tx (
    input  wire              clk,
    input  wire              rst_n,          // active-low synchronous reset

    input  wire              tx_start,
    input  wire [6:0]        tx_len,
    output wire [6:0]        psdu_idx,
    input  wire [7:0]        psdu_data,
    input  wire              tx_tick,

    output reg  signed [7:0] tx_dev,
    output reg               tx_valid,
    output reg               tx_active,
    output reg               tx_done,
    output reg               tx_reject
);
    localparam [1:0] S_IDLE = 2'd0, S_RUN = 2'd1, S_TAIL = 2'd2, S_END = 2'd3;
    localparam [6:0] MAX_PAYLOAD = 7'd125;

    // chip sequence of data symbol 0, first-transmitted chip (c0) at index 0
    localparam [31:0] BASE = 32'b11011001110000110101001000101110;

    // chip ci of symbol s: symbols 0..7 rotate symbol 0 right by 4*s chips,
    // symbols 8..15 additionally invert the odd-indexed chips
    function chip_of(input [3:0] s, input [4:0] ci);
        reg [4:0] idx;
        begin
            idx     = ci - {s[2:0], 2'b00};
            chip_of = BASE[31 - idx] ^ (s[3] & ci[0]);
        end
    endfunction

    // reflected CRC-16, bits LSB first, polynomial 0x8408 (init 0)
    function [15:0] crc_octet(input [15:0] c, input [7:0] b);
        integer k;
        reg [15:0] r;
        begin
            r = c ^ {8'h00, b};
            for (k = 0; k < 8; k = k + 1) r = (r >> 1) ^ (r[0] ? 16'h8408 : 16'h0000);
            crc_octet = r;
        end
    endfunction

    reg [1:0]  state;
    reg [6:0]  plen;        // payload octets
    reg [7:0]  oct_n;       // index of the octet being sent (0..6+plen+1)
    reg        hi;          // sending the high nibble of the octet
    reg [3:0]  oct_hi;      // high nibble of the current octet
    reg [3:0]  sym;         // current symbol
    reg [4:0]  ci;          // chip within the symbol
    reg [1:0]  wph;         // word within the chip interval
    reg        prev;        // previous chip
    reg        first;       // interval 0: no phase change
    reg        final_iv;    // interval after the last chip: no phase change
    reg [15:0] crc;

    wire [7:0] nx      = oct_n + 8'd1;                      // octet that follows
    wire [7:0] n_total = {1'b0, plen} + 8'd8;               // 4 + SFD + PHR + payload + 2 FCS
    wire [7:0] pl8     = {1'b0, plen};
    wire       nx_pay  = (nx >= 8'd6) && (nx < pl8 + 8'd6);

    assign psdu_idx = nx[6:0] - 7'd6;

    reg [7:0] next_oct;
    always @* begin
        if (nx < 8'd4)                 next_oct = 8'h00;
        else if (nx == 8'd4)           next_oct = 8'hA7;
        else if (nx == 8'd5)           next_oct = {1'b0, plen + 7'd2};
        else if (nx_pay)               next_oct = psdu_data;
        else if (nx == pl8 + 8'd6)     next_oct = crc[7:0];
        else                           next_oct = crc[15:8];
    end

    wire cur_chip = chip_of(sym, ci);
    wire same     = (cur_chip == prev);                      // c_k * c_{k-1} = +1
    wire neg      = ci[0] ? ~same : same;                    // sign -1 (even k: -p, odd k: +p)
    wire signed [7:0] word = (first || final_iv) ? 8'sd0 : (neg ? -8'sd64 : 8'sd64);

    always @(posedge clk) begin
        tx_valid  <= 1'b0;
        tx_dev    <= 8'sd0;
        tx_done   <= 1'b0;
        tx_reject <= 1'b0;
        if (!rst_n) begin
            state     <= S_IDLE;
            tx_active <= 1'b0;
            plen      <= 7'd0;
            oct_n     <= 8'd0;
            hi        <= 1'b0;
            oct_hi    <= 4'd0;
            sym       <= 4'd0;
            ci        <= 5'd0;
            wph       <= 2'd0;
            prev      <= 1'b0;
            first     <= 1'b1;
            final_iv  <= 1'b0;
            crc       <= 16'd0;
        end else begin
            if (tx_start) begin
                if (state != S_IDLE || tx_len > MAX_PAYLOAD) begin
                    tx_reject <= 1'b1;
                end else begin
                    state    <= S_RUN;
                    plen     <= tx_len;
                    oct_n    <= 8'd0;
                    hi       <= 1'b0;
                    oct_hi   <= 4'h0;
                    sym      <= 4'd0;
                    ci       <= 5'd0;
                    wph      <= 2'd0;
                    prev     <= 1'b0;
                    first    <= 1'b1;
                    final_iv <= 1'b0;
                    crc      <= 16'd0;
                end
            end else if (tx_tick) begin
                case (state)
                    S_RUN: begin
                        tx_valid  <= 1'b1;
                        tx_dev    <= word;
                        tx_active <= 1'b1;
                        wph       <= wph + 2'd1;
                        if (wph == 2'd3) begin
                            // end of a chip interval: the current chip becomes the previous one
                            prev  <= cur_chip;
                            first <= 1'b0;
                            if (final_iv) begin
                                state <= S_TAIL;
                            end else begin
                                ci <= ci + 5'd1;
                                if (ci == 5'd31) begin
                                    if (!hi) begin
                                        hi  <= 1'b1;
                                        sym <= oct_hi;
                                    end else begin
                                        hi    <= 1'b0;
                                        oct_n <= nx;
                                        oct_hi <= next_oct[7:4];
                                        sym   <= next_oct[3:0];
                                        if (nx_pay) crc <= crc_octet(crc, psdu_data);
                                        if (nx == n_total) final_iv <= 1'b1;
                                    end
                                end
                            end
                        end
                    end
                    S_TAIL: begin       // the sample after the last word: still active
                        state <= S_END;
                    end
                    S_END: begin
                        tx_active <= 1'b0;
                        tx_done   <= 1'b1;
                        state     <= S_IDLE;
                    end
                    default: ;
                endcase
            end
        end
    end
endmodule
