// LE 1M RX stage 4: access-address acquisition (model: find_sync) and the
// RSSI window (model: _rssi), plus the sample history the packet engine reads.
//
// The symbol-spaced sums s[n] arrive one per `in_valid`; `n_cnt` counts them.
// Once 313 are held, every new sample evaluates the 40 symbol-spaced taps
// v_j = s[k + 8j], k = n - 312, against the preamble + access-address pattern:
//   D    = (v_0 + ... + v_7) >> 3                   (floor)
//   corr = sum_j p_j (v_j - D),  mag = sum_j |v_j - D|
//   hit  = corr >= 4096*40  &&  8*corr >= 7*mag
// The first hit k0 opens a candidate window of 8 positions (k0 .. k0+7); the
// largest corr wins, the earliest on a tie (numpy argmax). `found` pulses once
// with the winner's sample index and sums. The pipeline is fully strobe driven
// and has no minimum gap between `in_valid` strobes.
//
// `flush` (end of capture, after the pipeline drained) closes a candidate
// window early, the way the model clips it at the end of the stimulus.
module le1m_rx_sync #(
    parameter HIST_W = 44                      // samples exported to the packet engine
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    input  wire signed [18:0] in_s,
    input  wire        [8:0]  in_mag,          // filtered |I|,|Q| magnitude of the same sample
    input  wire        [31:0] access_address,
    input  wire               flush,
    input  wire               pkt_done,        // packet engine finished: search again

    output reg         [31:0] n_cnt,           // samples received so far
    output wire [HIST_W*19-1:0] hist,          // hist[j*19 +: 19] = s[n_cnt-1-j]

    output reg                found,           // one-cycle pulse
    output reg                found_flush,     // found was forced by flush (follows `found`)
    output reg         [31:0] found_t,         // sync sample index (last access-address symbol)
    output reg signed [31:0]  found_corr,
    output reg signed [31:0]  found_sumv,      // sum of the 40 taps at the winner
    output reg         [19:0] found_w          // RSSI window sum ending at found_t
);
    localparam SPAN  = 312;                    // 8 * 39
    localparam DEPTH = SPAN + 1;
    localparam RW    = 320;                    // RSSI window, samples

    localparam S_SEARCH = 2'd0, S_ARG = 2'd1, S_HOLD = 2'd2;

    // --- pattern ----------------------------------------------------------
    wire [39:0] pat = {access_address, access_address[0] ? 8'h55 : 8'hAA};

    // --- history and RSSI window -----------------------------------------
    reg [DEPTH*19-1:0] hv;                     // hv[j*19 +: 19] = s[n_cnt-1-j]
    reg [8:0]  magmem [0:RW-1];
    reg [8:0]  wp;
    reg [19:0] wsum;

    wire [8:0]  mag_old = (n_cnt >= RW) ? magmem[wp] : 9'd0;
    wire [19:0] wsum_next = wsum + {11'd0, in_mag} - {11'd0, mag_old};

    assign hist = hv[HIST_W*19-1:0];

    always @(posedge clk) begin
        if (!rst_n) begin
            n_cnt <= 32'd0;
            wp    <= 9'd0;
            wsum  <= 20'd0;
        end else if (in_valid) begin
            n_cnt <= n_cnt + 32'd1;
            hv    <= {hv[(DEPTH-1)*19-1:0], in_s};
            magmem[wp] <= in_mag;
            wp    <= (wp == RW - 1) ? 9'd0 : wp + 9'd1;
            wsum  <= wsum_next;
        end
    end

    // --- metric stage (cycle after the shift) ------------------------------
    // Evaluated from the shifted history one cycle after the strobe, so the
    // result belongs to sample n_cnt-1 even if the next strobe is already due.
    reg               strobe_d;
    reg               m_valid;
    reg signed [31:0] m_corr, m_sumv;
    reg        [19:0] m_w;
    reg        [31:0] m_t;
    reg               m_ok;

    // sign-extended history word idx of a packed history vector
    function signed [31:0] hx(input [DEPTH*19-1:0] v, input integer idx);
        hx = {{13{v[idx*19+18]}}, v[idx*19 +: 19]};
    endfunction

    // {sumv, mag, corr} of the 40 taps ending at the newest sample
    function [95:0] metrics(input [DEPTH*19-1:0] v);
        integer           jj;
        reg signed [31:0] sum8, sumv, d, w, corr, mag;
        begin
            sum8 = 0;
            sumv = 0;
            for (jj = 0; jj < 40; jj = jj + 1) begin
                sumv = sumv + hx(v, SPAN - 8*jj);
                if (jj < 8) sum8 = sum8 + hx(v, SPAN - 8*jj);
            end
            d    = sum8 >>> 3;
            corr = 0;
            mag  = 0;
            for (jj = 0; jj < 40; jj = jj + 1) begin
                w    = hx(v, SPAN - 8*jj) - d;
                corr = pat[jj] ? corr + w : corr - w;
                mag  = mag + ((w < 0) ? -w : w);
            end
            metrics = {sumv, mag, corr};
        end
    endfunction

    // Combinational view of the shifted history; only the registered results
    // below are used sequentially, so the clocked block has no blocking writes.
    wire [95:0]        met = metrics(hv);
    wire signed [31:0] met_corr = met[31:0];
    wire signed [31:0] met_mag  = met[63:32];
    wire signed [31:0] met_sumv = met[95:64];

    always @(posedge clk) begin
        strobe_d <= rst_n & in_valid;
        m_valid  <= 1'b0;
        if (rst_n && strobe_d) begin
            m_valid <= 1'b1;
            m_corr  <= met_corr;
            m_sumv  <= met_sumv;
            m_w     <= wsum;
            m_t     <= n_cnt - 32'd1;
            m_ok    <= (n_cnt >= DEPTH)
                       && (met_corr >= 32'sd163840)
                       && ((met_corr <<< 3) >= 7 * met_mag);
        end
    end

    // --- search / candidate window ----------------------------------------
    reg [1:0]         state;
    reg [2:0]         acnt;                    // candidates seen so far, minus one
    reg signed [31:0] b_corr, b_sumv;
    reg        [19:0] b_w;
    reg        [31:0] b_t;

    wire upd = m_corr > b_corr;

    always @(posedge clk) begin
        found       <= 1'b0;
        found_flush <= 1'b0;
        if (!rst_n) begin
            state <= S_SEARCH;
            acnt  <= 3'd0;
        end else begin
            case (state)
                S_SEARCH: if (m_valid && m_ok) begin
                    b_corr <= m_corr;
                    b_sumv <= m_sumv;
                    b_w    <= m_w;
                    b_t    <= m_t;
                    acnt   <= 3'd0;
                    state  <= S_ARG;
                end
                S_ARG: begin
                    if (m_valid) begin
                        if (upd) begin
                            b_corr <= m_corr;
                            b_sumv <= m_sumv;
                            b_w    <= m_w;
                            b_t    <= m_t;
                        end
                        acnt <= acnt + 3'd1;
                        if (acnt == 3'd6) begin           // eighth candidate
                            found      <= 1'b1;
                            found_t    <= upd ? m_t : b_t;
                            found_corr <= upd ? m_corr : b_corr;
                            found_sumv <= upd ? m_sumv : b_sumv;
                            found_w    <= upd ? m_w : b_w;
                            state      <= S_HOLD;
                        end
                    end else if (flush) begin
                        found       <= 1'b1;
                        found_flush <= 1'b1;
                        found_t     <= b_t;
                        found_corr  <= b_corr;
                        found_sumv  <= b_sumv;
                        found_w     <= b_w;
                        state       <= S_HOLD;
                    end
                end
                default: if (pkt_done) state <= S_SEARCH;   // S_HOLD
            endcase
        end
    end
endmodule
