// LE 1M RX stage 5: packet engine (model: the second half of demodulate).
//
// Starts on the acquisition result, then walks the symbols of the packet:
// hard decision at the symbol sample, data-directed offset tracker, early-late
// timing loop, optional de-whitening, header length parse and bit-serial
// CRC-24. Everything is keyed to the absolute sample index t, not to clock
// cycles: a symbol is processed once s[t+2] exists, reading s[t-2], s[t], s[t+2]
// from the sample history at offset (n_cnt - 1 - index), so the engine may lag
// the sample stream (initialisation takes ~12 clk) without changing a result.
//
// Trace events (decision 0007 taps) leave on a one-event-per-clk bus; the
// bus index is the sample index of the model's record, not a time.
module le1m_rx_pkt #(
    parameter HIST_W = 44
) (
    input  wire                 clk,
    input  wire                 rst_n,

    input  wire                 found,
    input  wire                 found_flush,
    input  wire [31:0]          found_t,
    input  wire signed [31:0]   found_corr,
    input  wire signed [31:0]   found_sumv,
    input  wire [19:0]          found_w,
    input  wire [31:0]          n_cnt,
    input  wire [HIST_W*19-1:0] hist,
    input  wire                 flush,

    input  wire [31:0]          access_address,
    input  wire [23:0]          crc_init,
    input  wire                 dewhiten_en,
    input  wire [5:0]           chan,

    output reg                  ev_valid,
    output reg  [3:0]           ev_kind,
    output reg  [31:0]          ev_index,
    output reg  [23:0]          ev_value,

    output reg                  done,        // one-cycle pulse, packet (or truncated packet) finished
    output reg                  crc_ok,
    output reg                  rssi_valid,
    output reg  [8:0]           rssi_lin,
    output reg                  agc_hold,
    output reg                  lag_overrun  // sticky: the engine fell further behind than the history window
);
    localparam K_BIT = 4'd1, K_SYNC = 4'd2, K_TBOUND = 4'd3, K_CFO = 4'd4,
               K_CRC = 4'd5, K_RSSI = 4'd6;

    localparam [4:0] P_IDLE = 5'd0,  P_I1 = 5'd1,  P_I2 = 5'd2,  P_I3 = 5'd3,
                     P_DIV = 5'd4,   P_EV_SYNC = 5'd5, P_EV_CFO = 5'd6,
                     P_WAIT = 5'd7,  P_CALC = 5'd8,
                     P_EM_BIT = 5'd9, P_EM_TBF = 5'd10, P_EM_TBS = 5'd11,
                     P_EM_CFO = 5'd12, P_EM_CRC = 5'd13, P_EM_RSSI = 5'd14,
                     P_TRL_INIT = 5'd15, P_TRL = 5'd16, P_FIN = 5'd17;

    localparam [23:0] CRC_POLY = 24'h00065B;
    localparam [31:0] SPS = 32'd8;
    localparam [31:0] TIMING_SPAN = 32'd2;
    localparam signed [31:0] TIMING_THRESHOLD = 32'sd48;
    localparam [31:0] HOFF_MAX = HIST_W - 5;    // largest offset with offset+4 in the window

    reg [4:0] state;

    // acquisition result
    reg signed [31:0] corr_r, sumv_r;
    reg        [19:0] w_r;
    reg signed [47:0] a_r;
    reg signed [31:0] amp;
    reg        [4:0]  inv_a;
    reg        [2:0]  dcnt;
    reg        [31:0] rem;

    // packet state
    reg [31:0]        t;
    reg signed [31:0] d;
    reg signed [31:0] tacc;
    reg [11:0]        sym, want, pdu_end;
    reg [6:0]         len_r;           // header bits 8..14; bit 15 is used as it is decoded
    reg [23:0]        crc_r, crc_rx;
    reg [6:0]         lfsr;
    reg [31:0]        tb_buf [0:15];
    reg [11:0]        kk;
    reg               flushed;

    // captured samples for one symbol
    reg signed [18:0] s0, sp, sm;

    // emission registers
    reg [31:0] e_tpre, e_tnew;
    reg [11:0] e_k;
    reg        e_b, e_tbf, e_step, e_cfo, e_done;
    reg [23:0] e_dval;

    // ---- combinational helpers -------------------------------------------
    function signed [7:0] pattern_sum(input [31:0] aa);   // sum of the +/-1 pattern
        integer ii, pc;
        begin
            pc = 4;                                        // preamble 0x55 / 0xAA: four ones
            for (ii = 0; ii < 32; ii = ii + 1) pc = pc + {31'd0, aa[ii]};
            pattern_sum = pc[7:0] + pc[7:0] - 8'd40;
        end
    endfunction

    function [23:0] clip24(input signed [31:0] x);
        begin
            if (x > 32'sd8388607)        clip24 = 24'h7FFFFF;
            else if (x < -32'sd8388608)  clip24 = 24'h800000;
            else                         clip24 = x[23:0];
        end
    endfunction

    wire signed [7:0] psum = pattern_sum(access_address);

    // symbol arithmetic (valid in P_CALC)
    wire [31:0]        tn      = t + SPS;
    wire signed [31:0] s0x     = {{13{s0[18]}}, s0};
    wire signed [31:0] spx     = {{13{sp[18]}}, sp};
    wire signed [31:0] smx     = {{13{sm[18]}}, sm};
    wire signed [31:0] v       = s0x - d;
    wire               b0      = (v > 0);
    wire               b       = b0 ^ (dewhiten_en & lfsr[0]);
    wire signed [31:0] spd     = spx - d;
    wire signed [31:0] smd     = smx - d;
    wire signed [31:0] e_err   = ((spd < 0) ? -spd : spd) - ((smd < 0) ? -smd : smd);
    /* verilator lint_off UNUSEDSIGNAL */
    wire signed [47:0] prod    = e_err * $signed({27'd0, inv_a});   // only prod[43:12] is used
    /* verilator lint_on UNUSEDSIGNAL */
    wire signed [31:0] tacc_p  = tacc + prod[43:12];
    wire               up_step = (tacc_p >= TIMING_THRESHOLD);
    wire               dn_step = (tacc_p <= -TIMING_THRESHOLD);
    wire signed [31:0] tacc_n  = up_step ? tacc_p - TIMING_THRESHOLD
                               : dn_step ? tacc_p + TIMING_THRESHOLD : tacc_p;
    wire [31:0]        t_new   = up_step ? tn + 32'd1 : dn_step ? tn - 32'd1 : tn;
    wire signed [31:0] d_new   = d + ((v - (b0 ? amp : -amp)) >>> 6);
    wire [11:0]        sym_n   = sym + 12'd1;
    wire [11:0]        len_pdu = 12'd16 + {1'b0, b, len_r, 3'b000};   // 16 + 8*length at sym 15
    wire [11:0]        want_n  = (sym == 12'd15) ? len_pdu + 12'd24 : want;
    wire [11:0]        pdu_n   = (sym == 12'd15) ? len_pdu : pdu_end;
    wire               crc_fb  = crc_r[23] ^ b;

    // readiness: s[tn+2] has arrived  <=>  n_cnt - 1 >= tn + 2
    wire [31:0] tn_w     = t + SPS;
    wire        rdy      = (n_cnt >= tn_w + TIMING_SPAN + 32'd1);
    wire [31:0] off_raw  = n_cnt - tn_w - TIMING_SPAN - 32'd1;
    wire        off_over = (off_raw > HOFF_MAX);
    wire [31:0] off      = off_over ? HOFF_MAX : off_raw;

    function signed [18:0] hist_at(input [31:0] idx);
        begin
            hist_at = hist[idx*19 +: 19];
        end
    endfunction

    // offset estimate at sync: round-half-up on the magnitude, sign restored
    wire signed [63:0] dk0 = {{32{sumv_r[31]}}, sumv_r} - a_r * psum;
    wire signed [63:0] dk_pos = (dk0 * 64'sd1639 + 64'sd32768) >>> 16;
    wire signed [63:0] dk_neg = ((-dk0) * 64'sd1639 + 64'sd32768) >>> 16;
    /* verilator lint_off UNUSEDSIGNAL */
    wire signed [63:0] dk_round = (dk0 >= 0) ? dk_pos : -dk_neg;      // fits 32 bits; upper half unused
    /* verilator lint_on UNUSEDSIGNAL */

    // RSSI: (window sum * 205 + 2^15) >> 16
    /* verilator lint_off UNUSEDSIGNAL */
    wire [31:0] rssi_calc = {12'd0, w_r} * 32'd205 + 32'd32768;       // result is bits [24:16]
    /* verilator lint_on UNUSEDSIGNAL */

    always @(posedge clk) begin
        ev_valid   <= 1'b0;
        done       <= 1'b0;
        rssi_valid <= 1'b0;
        if (!rst_n) begin
            state       <= P_IDLE;
            agc_hold    <= 1'b0;
            lag_overrun <= 1'b0;
            flushed     <= 1'b0;
            crc_ok      <= 1'b0;
            rssi_lin    <= 9'd0;
        end else begin
            if (flush && state != P_IDLE) flushed <= 1'b1;
            case (state)
                P_IDLE: if (found) begin
                    t       <= found_t;
                    corr_r  <= found_corr;
                    sumv_r  <= found_sumv;
                    w_r     <= found_w;
                    flushed <= found_flush | flush;
                    state   <= P_I1;
                end
                P_I1: begin
                    a_r   <= (corr_r * 48'sd1639 + 48'sd32768) >>> 16;      // ~ corr / 40
                    state <= P_I2;
                end
                P_I2: begin
                    amp <= (a_r < 48'sd1) ? 32'sd1 : a_r[31:0];
                    d   <= dk_round[31:0];
                    state <= P_I3;
                end
                P_I3: begin
                    rssi_lin <= rssi_calc[24:16];
                    rem      <= 32'd65536;
                    inv_a    <= 5'd0;
                    dcnt     <= 3'd4;
                    state    <= P_DIV;
                end
                P_DIV: begin                                   // inv_a = floor(65536 / amp), 5 bits
                    if (rem >= (amp[31:0] << dcnt)) begin
                        rem        <= rem - (amp[31:0] << dcnt);
                        inv_a[dcnt] <= 1'b1;
                    end
                    dcnt <= dcnt - 3'd1;
                    if (dcnt == 3'd0) state <= P_EV_SYNC;
                end
                P_EV_SYNC: begin
                    ev_valid <= 1'b1;
                    ev_kind  <= K_SYNC;
                    ev_index <= t;
                    ev_value <= 24'd1;
                    state    <= P_EV_CFO;
                end
                P_EV_CFO: begin
                    ev_valid <= 1'b1;
                    ev_kind  <= K_CFO;
                    ev_index <= t;
                    ev_value <= clip24(d);
                    sym      <= 12'd0;
                    tacc     <= 32'sd0;
                    want     <= 12'd16;
                    pdu_end  <= 12'd16;
                    len_r    <= 7'd0;
                    crc_r    <= crc_init;
                    crc_rx   <= 24'd0;
                    lfsr     <= {1'b1, chan[5:0]};
                    agc_hold <= 1'b1;
                    state    <= P_WAIT;
                end
                P_WAIT: begin
                    if (rdy) begin
                        if (off_over) lag_overrun <= 1'b1;
                        s0 <= hist_at(off + 32'd2);
                        sp <= hist_at(off);
                        sm <= hist_at(off + 32'd4);
                        state <= P_CALC;
                    end else if (flushed || flush) begin
                        state <= P_TRL_INIT;
                    end
                end
                P_CALC: begin
                    tb_buf[sym[3:0]] <= tn;
                    e_tpre <= tn;
                    e_tnew <= t_new;
                    e_k    <= sym;
                    e_b    <= b;
                    e_tbf  <= (sym < 12'd16);
                    e_step <= up_step | dn_step;
                    e_cfo  <= (sym_n[4:0] == 5'd0);
                    e_dval <= clip24(d_new);
                    e_done <= (sym_n == want_n);
                    t      <= t_new;
                    tacc   <= tacc_n;
                    d      <= d_new;
                    sym    <= sym_n;
                    want   <= want_n;
                    pdu_end <= pdu_n;
                    if (sym >= 12'd8 && sym < 12'd15) len_r[sym[2:0]] <= b;
                    if (sym < pdu_end)      crc_r  <= {crc_r[22:0], 1'b0} ^ (crc_fb ? CRC_POLY : 24'd0);
                    else if (sym < want)    crc_rx <= {crc_rx[22:0], b};
                    lfsr <= {1'b0, lfsr[6:1]} ^ (lfsr[0] ? 7'h44 : 7'h00);
                    state <= P_EM_BIT;
                end
                P_EM_BIT: begin
                    ev_valid <= 1'b1;
                    ev_kind  <= K_BIT;
                    ev_index <= e_tpre;
                    ev_value <= {23'd0, e_b};
                    state    <= P_EM_TBF;
                end
                P_EM_TBF: begin
                    if (e_tbf) begin
                        ev_valid <= 1'b1;
                        ev_kind  <= K_TBOUND;
                        ev_index <= e_tpre;
                        ev_value <= {12'd0, e_k};
                    end
                    state <= P_EM_TBS;
                end
                P_EM_TBS: begin
                    if (e_step) begin
                        ev_valid <= 1'b1;
                        ev_kind  <= K_TBOUND;
                        ev_index <= e_tnew;
                        ev_value <= {12'd0, e_k};
                    end
                    state <= P_EM_CFO;
                end
                P_EM_CFO: begin
                    if (e_cfo) begin
                        ev_valid <= 1'b1;
                        ev_kind  <= K_CFO;
                        ev_index <= e_tnew;
                        ev_value <= e_dval;
                    end
                    state <= e_done ? P_EM_CRC : P_WAIT;
                end
                P_EM_CRC: begin
                    ev_valid <= 1'b1;
                    ev_kind  <= K_CRC;
                    ev_index <= e_tpre;
                    ev_value <= {23'd0, crc_r == crc_rx};
                    crc_ok   <= (crc_r == crc_rx);
                    state    <= P_EM_RSSI;
                end
                P_EM_RSSI: begin
                    ev_valid   <= 1'b1;
                    ev_kind    <= K_RSSI;
                    ev_index   <= e_tpre;
                    ev_value   <= {15'd0, rssi_lin};
                    rssi_valid <= 1'b1;
                    state      <= P_TRL_INIT;
                end
                P_TRL_INIT: begin                              // last 16 boundaries not yet emitted
                    kk    <= (sym >= 12'd32) ? sym - 12'd16 : 12'd16;
                    state <= P_TRL;
                end
                P_TRL: begin
                    if (kk < sym) begin
                        ev_valid <= 1'b1;
                        ev_kind  <= K_TBOUND;
                        ev_index <= tb_buf[kk[3:0]];
                        ev_value <= {12'd0, kk};
                        kk       <= kk + 12'd1;
                    end else begin
                        state <= P_FIN;
                    end
                end
                default: begin                                 // P_FIN
                    done     <= 1'b1;
                    agc_hold <= 1'b0;
                    flushed  <= 1'b0;
                    state    <= P_IDLE;
                end
            endcase
        end
    end
endmodule
