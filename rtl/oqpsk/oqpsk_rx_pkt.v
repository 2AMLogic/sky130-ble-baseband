// 802.15.4 O-QPSK RX stage 6: symbol decisions, timing tracking, PHR length,
// octet assembly, FCS check, and the trace taps (model: the decode loop of
// oqpsk_rx.demodulate).
//
// After `found` (SFD's last symbol at correlator index t0), one symbol is
// decided every 128 correlator indices, at index t: argmax over the 16
// correlators (lowest index on ties) at t, then t moves by -1 / +1 for the
// next symbol if the neighbour of the decided correlator strictly beats it
// (the model's timing step). The decision needs index t+1, so it is taken in
// the cycle the result for t+1 arrives; a capture that ends first stops the
// loop, exactly as the model's `t + 1 >= ncorr` break.
//
// Symbols 0 and 1 are the PHR (length = 7 bits, reserved bit ignored); then
// 2*length symbols, two per octet, low nibble first. The FCS is checked by
// running the CRC over every PSDU octet, FCS included (init 0, reflected
// 0x8408, little-endian FCS): the residue is 0 exactly when the model's
// crc16_fcs(psdu[:-2]) equals the last two octets. PSDUs of fewer than 2
// octets report crc 0.
//
// Trace taps (ev_*), kinds: 2 sync, 3 tbound, 5 crc, 6 rssi, 7 octet (kinds 1
// bit and 4 cfo of the LE receiver do not exist here). Each decision queues
// its records and they leave one per clk, at most 21 clk after the decision;
// the next decision is >= 127 results later. Record indices are the model's
// sample indices:
//   sync    c_n at the SFD result
//   tbound  chips 0..15 of the first symbol, chips 16..31 of the last symbol
//           (sample base - 4*(31-k), base = t + 120, value 32*sym + k), and a
//           step record at base +/- 1 with value 32*sym + 31
//   octet   base of the octet's second symbol; crc, rssi at the last symbol's base
//   rssi    (sum of 320 magnitudes ending at the sync sample * 205 + 2^15) >> 16
// `gain` records echo the stimulus and are not produced here (as le1m_rx).
module oqpsk_rx_pkt (
    input  wire               clk,
    input  wire               rst_n,

    input  wire               c_valid,
    input  wire [31:0]        c_n,
    input  wire [16*23-1:0]   c_vec,
    input  wire [3:0]         c_best,
    input  wire [16:0]        c_rsum,
    input  wire               found,
    input  wire               flush,

    output reg                ev_valid,
    output reg  [3:0]         ev_kind,
    output reg  [31:0]        ev_index,
    output reg  [23:0]        ev_value,

    output reg                pkt_done,       // one-cycle pulse: packet complete, or the capture ended
    output reg                pkt_synced,     // sticky: an SFD was found
    output reg                pkt_crc_ok,     // valid after pkt_done
    output reg                rssi_valid,     // one-cycle pulse with rssi_lin
    output reg  [8:0]         rssi_lin,
    output wire               agc_hold
);
    localparam [1:0] P_IDLE = 2'd0, P_DEC = 2'd1, P_DONE = 2'd2;

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
    reg [7:0]  dly;
    reg [16*23-1:0] cv1, cv2;       // results for t and t-1 (c_vec is t+1)
    reg [3:0]  best1;               // argmax at t
    reg [8:0]  symcnt;              // symbols decided so far
    reg [8:0]  nsym;                // 2 + 2*length once known
    reg [3:0]  psym;                // previous symbol
    reg [15:0] crc;
    reg [16:0] rsum_l;              // RSSI window sum at the sync sample
    reg        done_req, done_sent;

    // --- the decision --------------------------------------------------------
    wire [3:0] m = best1;
    wire signed [22:0] va = cv2[m*23 +: 23];
    wire signed [22:0] vb = cv1[m*23 +: 23];
    wire signed [22:0] vc = c_vec[m*23 +: 23];
    wire step_dn = (va > vb) && (va >= vc);
    wire step_up = !step_dn && (vc > vb);
    wire [1:0] step = step_dn ? 2'b11 : step_up ? 2'b01 : 2'b00;     // two's complement -1, +1, 0

    wire        decide = c_valid && (state == P_DEC) && (dly == 8'd0);
    wire [6:0]  len_n  = {m[2:0], psym};                              // valid when symcnt == 1
    wire [8:0]  nsym_n = (symcnt == 9'd1) ? 9'd2 + {len_n, 1'b0} : nsym;
    wire        len_ge2 = (nsym_n >= 9'd6);                           // length >= 2
    wire        is_first = (symcnt == 9'd0);
    wire        is_last  = (symcnt != 9'd0) && (symcnt + 9'd1 == nsym_n);
    wire        oct_v    = symcnt[0] && (symcnt >= 9'd3);
    wire [15:0] crc_n    = oct_v ? crc_octet(crc, {m, psym}) : crc;
    wire [24:0] rssi_p   = {8'd0, rsum_l} * 25'd205 + 25'd32768;
    wire        _unused_rssi = &{1'b0, rssi_p[15:0]};

    // --- the record burst ----------------------------------------------------
    reg        b_act, b_sync, b_oct_v, b_crc_v, b_crc, b_rssi_v;
    reg [1:0]  b_step;
    reg [1:0]  b_edge;              // 0 none, 1 chips 0..15, 2 chips 16..31
    reg [7:0]  b_sym;
    reg [31:0] b_idx;
    reg [7:0]  b_oct;
    reg [8:0]  b_rssi;
    reg [4:0]  ph;

    wire [4:0] kk = {(b_edge == 2'd2), 4'd0} + {1'b0, ph[3:0] - 4'd2};   // chip within the symbol, ph 2..17
    wire [31:0] step_idx = b_step[1] ? b_idx - 32'd1 : b_idx + 32'd1;

    assign agc_hold = (state == P_DEC);

    always @(posedge clk) begin
        ev_valid   <= 1'b0;
        pkt_done   <= 1'b0;
        rssi_valid <= 1'b0;
        if (!rst_n) begin
            state      <= P_IDLE;
            dly        <= 8'd0;
            cv1        <= {16*23{1'b0}};
            cv2        <= {16*23{1'b0}};
            best1      <= 4'd0;
            symcnt     <= 9'd0;
            nsym       <= 9'd2;
            psym       <= 4'd0;
            crc        <= 16'd0;
            rsum_l     <= 17'd0;
            done_req   <= 1'b0;
            done_sent  <= 1'b0;
            pkt_synced <= 1'b0;
            pkt_crc_ok <= 1'b0;
            rssi_lin   <= 9'd0;
            b_act      <= 1'b0;
            ph         <= 5'd0;
        end else begin
            if (c_valid) begin
                cv2   <= cv1;
                cv1   <= c_vec;
                best1 <= c_best;
                if (state == P_DEC && dly != 8'd0) dly <= dly - 8'd1;
            end

            if (found) begin
                state      <= P_DEC;
                pkt_synced <= 1'b1;
                dly        <= 8'd128;
                rsum_l     <= c_rsum;
                symcnt     <= 9'd0;
                crc        <= 16'd0;
                b_act      <= 1'b1;
                b_sync     <= 1'b1;
                b_step     <= 2'b00;
                b_edge     <= 2'd0;
                b_oct_v    <= 1'b0;
                b_crc_v    <= 1'b0;
                b_rssi_v   <= 1'b0;
                b_idx      <= c_n;
                b_sym      <= 8'd0;
                ph         <= 5'd0;
            end

            if (decide) begin
                symcnt <= symcnt + 9'd1;
                nsym   <= nsym_n;
                psym   <= m;
                crc    <= crc_n;
                dly    <= 8'd127 + {{6{step[1]}}, step};
                b_act    <= 1'b1;
                b_sync   <= 1'b0;
                b_step   <= step;
                b_edge   <= is_first ? 2'd1 : is_last ? 2'd2 : 2'd0;
                b_sym    <= symcnt[7:0];
                b_idx    <= c_n - 32'd1;                      // t + 120
                b_oct_v  <= oct_v;
                b_oct    <= {m, psym};
                b_crc_v  <= is_last;
                b_crc    <= len_ge2 && (crc_n == 16'd0);
                b_rssi_v <= is_last && len_ge2;
                b_rssi   <= rssi_p[24:16];
                ph       <= 5'd0;
                if (is_last) begin
                    state      <= P_DONE;
                    pkt_crc_ok <= len_ge2 && (crc_n == 16'd0);
                    rssi_lin   <= rssi_p[24:16];
                    done_req   <= 1'b1;
                end
            end

            if (flush && !done_sent) done_req <= 1'b1;

            if (b_act && !found && !decide) begin
                ph <= ph + 5'd1;
                case (ph)
                    5'd0: if (b_sync) begin
                        ev_valid <= 1'b1; ev_kind <= 4'd2; ev_index <= b_idx; ev_value <= 24'd1;
                    end
                    5'd1: if (b_step != 2'b00) begin
                        ev_valid <= 1'b1; ev_kind <= 4'd3; ev_index <= step_idx;
                        ev_value <= {11'd0, b_sym, 5'd31} ;
                    end
                    5'd18: if (b_oct_v) begin
                        ev_valid <= 1'b1; ev_kind <= 4'd7; ev_index <= b_idx; ev_value <= {16'd0, b_oct};
                    end
                    5'd19: if (b_crc_v) begin
                        ev_valid <= 1'b1; ev_kind <= 4'd5; ev_index <= b_idx; ev_value <= {23'd0, b_crc};
                    end
                    5'd20: begin
                        if (b_rssi_v) begin
                            ev_valid <= 1'b1; ev_kind <= 4'd6; ev_index <= b_idx; ev_value <= {15'd0, b_rssi};
                            rssi_valid <= 1'b1;
                        end
                        b_act <= 1'b0;
                    end
                    default: if (ph >= 5'd2 && ph <= 5'd17 && b_edge != 2'd0) begin
                        ev_valid <= 1'b1; ev_kind <= 4'd3;
                        ev_index <= b_idx - 32'd124 + {25'd0, kk, 2'b00};
                        ev_value <= {11'd0, b_sym, 5'd0} + {19'd0, kk};
                    end
                endcase
            end

            // done once the records of the last decision (or of the flush) have left
            if (done_req && !done_sent && !b_act && !decide && !found) begin
                pkt_done  <= 1'b1;
                done_sent <= 1'b1;
                done_req  <= 1'b0;
                if (state != P_DONE) state <= P_DONE;
            end
        end
    end
endmodule
