// LE 1M transmit path: PDU octets in, `tx_dev` words out at 8 Msps on a
// 4-clock grid (32 MHz clock), per spec/frontend-interface.md 3.2 and
// decisions 0005 / 0007. Bit-exact with tx_dev_words() in
// sim/model/le1m_tx.py, including the 32 trailing drain words
// (word count = 8 * nbits + 32).
//
// Timing, per 4-clock sample slot (ph = 0..3):
//   ph 0: take the next sample into the shaper (new symbol bit every 8 slots)
//   ph 1: register tx_dev, pulse tx_valid, raise tx_active on the first word
//   ph 2: tx_valid falls
// tx_active is high from the first word through one slot after the last word.
// There is no back-pressure; `start` while busy is ignored.
//
// Input side: a plain PDU-octet pull interface local to this block
// (pdu_ready / pdu_valid / pdu_data). Octets must arrive before they are
// consumed; otherwise `underrun` sets.
module le1m_tx (
    input  wire        clk,
    input  wire        rst_n,           // active-low synchronous reset
    input  wire        start,           // one-cycle pulse; parameters sampled now
    input  wire [31:0] access_address,
    input  wire [5:0]  channel,
    input  wire [23:0] crc_init,
    input  wire [8:0]  pdu_len,         // octets, 0..257
    output wire        pdu_ready,
    input  wire        pdu_valid,
    input  wire [7:0]  pdu_data,
    output reg  [7:0]  tx_dev,          // signed; 0 when idle
    output reg         tx_valid,
    output reg         tx_active,
    output wire        busy,
    output wire        underrun
);
    reg        run;
    reg [1:0]  ph;
    reg [2:0]  smp;       // sample index within the current symbol
    reg        in_syms;   // symbols still being produced
    reg        final_sym; // the symbol being held is the last one
    reg        sym_q;     // current symbol bit
    reg [5:0]  tail;      // slots since the last symbol ended
    reg        emit;      // this slot yields a tx_dev word
    reg        fin;       // this slot ends tx_active

    wire start_ok = start & ~run;
    wire ph0      = run & (ph == 2'd0);
    wire new_sym  = ph0 & in_syms & (smp == 3'd0);

    wire bit_out;
    wire bit_last;
    wire cur_bit = (smp == 3'd0) ? bit_out : sym_q;

    le1m_frame u_frame (
        .clk(clk), .rst_n(rst_n), .load(start_ok),
        .access_address(access_address), .channel(channel),
        .crc_init(crc_init), .pdu_len(pdu_len),
        .pdu_ready(pdu_ready), .pdu_valid(pdu_valid), .pdu_data(pdu_data),
        .bit_req(new_sym), .bit_out(bit_out), .bit_last(bit_last),
        .underrun(underrun)
    );

    wire signed [7:0] dev;

    le1m_gauss u_gauss (
        .clk(clk), .rst_n(rst_n), .clr(start_ok),
        .shift(ph0), .din(cur_bit), .dvalid(in_syms),
        .dev(dev)
    );

    assign busy = run;

    always @(posedge clk) begin
        if (!rst_n) begin
            run       <= 1'b0;
            ph        <= 2'd0;
            smp       <= 3'd0;
            in_syms   <= 1'b0;
            final_sym <= 1'b0;
            sym_q     <= 1'b0;
            tail      <= 6'd0;
            emit      <= 1'b0;
            fin       <= 1'b0;
            tx_dev    <= 8'd0;
            tx_valid  <= 1'b0;
            tx_active <= 1'b0;
        end else begin
            tx_valid <= 1'b0;
            if (start_ok) begin
                run       <= 1'b1;
                ph        <= 2'd0;
                smp       <= 3'd0;
                in_syms   <= 1'b1;
                final_sym <= 1'b0;
                tail      <= 6'd0;
                emit      <= 1'b0;
                fin       <= 1'b0;
            end else if (run) begin
                ph <= ph + 2'd1;
                case (ph)
                    2'd0: begin
                        emit <= in_syms | (tail < 6'd32);
                        fin  <= ~in_syms & (tail == 6'd33);
                        if (new_sym) begin
                            sym_q <= bit_out;
                            if (bit_last) final_sym <= 1'b1;
                        end
                        smp <= smp + 3'd1;
                        if (in_syms) begin
                            if (smp == 3'd7 && final_sym)
                                in_syms <= 1'b0;
                        end else begin
                            tail <= tail + 6'd1;
                        end
                    end
                    2'd1: begin
                        if (emit) begin
                            tx_dev    <= dev;
                            tx_valid  <= 1'b1;
                            tx_active <= 1'b1;
                        end
                        if (fin) begin
                            tx_dev    <= 8'd0;
                            tx_active <= 1'b0;
                            run       <= 1'b0;
                        end
                    end
                    default: ;
                endcase
            end
        end
    end
endmodule
