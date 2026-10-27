// 802.15.4 O-QPSK RX stage 4: chip-rate differential despreader (model:
// oqpsk_rx.correlate, _accept) and the RSSI window.
//
// For every integrated sample g[n] with n >= 120 this forms the 16 symbol
// correlators over the 31 chip-spaced taps ending at g[n] (tap j is
// g[n - 4*(30 - j)], weight W[m][j] = +/-1 from the chip table, transition
// k = j + 1), and mag = sum |tap|. The model's correlator index is i = n - 120;
// events elsewhere carry the sample index n (= i + WINDOW_END), so this block
// hands n along. One result per input strobe, however closely spaced, in two
// register stages (vector, then argmax/accept):
//
//   o_vec   16 x signed 23, exact          o_best  argmax, lowest index on ties
//   o_ok    corr_best >= 4096*31 and 4*corr_best >= 3*mag
//   o_rsum  sum of the last 320 sideband magnitudes ending at sample n (the
//           model's _rssi window, zero before sample 0), exact in 17 bits
//
// The 16 x 31 sums are written as one combinational expression per strobe:
// bit-exactness, not area or Fmax, is the goal here (items 1f/5 own those).
module oqpsk_rx_corr #(
    parameter SIDE_W = 9
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                in_valid,
    input  wire signed [17:0]  in_g,
    input  wire [SIDE_W-1:0]   in_mag,

    output reg                 o_valid,
    output reg  [31:0]         o_n,
    output reg  [16*23-1:0]    o_vec,
    output reg  [3:0]          o_best,
    output reg                 o_ok,
    output reg  [16:0]         o_rsum
);
    localparam NTAPS    = 31;
    localparam HIST     = 120;            // g[n-1] .. g[n-120]
    localparam RSSI_WIN = 320;

    // --- chip table (same as oqpsk_tx.v) and the weight matrix -----------------
    localparam [31:0] BASE = 32'b11011001110000110101001000101110;

    function chip_of(input [3:0] s, input [4:0] ci);
        reg [4:0] idx;
        begin
            idx     = ci - {s[2:0], 2'b00};
            chip_of = BASE[31 - idx] ^ (s[3] & ci[0]);
        end
    endfunction

    // bit m*31+j set: W[m][j] = -1. Transition k = j+1 turns the phase by
    // -c_k c_{k-1} (k even) or +c_k c_{k-1} (k odd).
    function [16*NTAPS-1:0] build_wneg(input dummy);
        integer m, j;
        reg [4:0] k;
        reg same;
        begin
            build_wneg = {16*NTAPS{dummy & 1'b0}};
            for (m = 0; m < 16; m = m + 1)
                for (j = 0; j < NTAPS; j = j + 1) begin
                    k    = j[4:0] + 5'd1;
                    same = (chip_of(m[3:0], k) == chip_of(m[3:0], k - 5'd1));
                    build_wneg[m*NTAPS + j] = k[0] ? ~same : same;
                end
        end
    endfunction
    localparam [16*NTAPS-1:0] WNEG = build_wneg(1'b0);

    // --- g history and the 31 taps ---------------------------------------------
    reg  [HIST*18-1:0] ghp;                // field d = g[n-1-d]
    reg  [31:0]        nin;                // index of the incoming sample

    reg signed [17:0]  tap [0:NTAPS-1];
    reg        [22:0]  msum;
    reg  [16*23-1:0]   vec_c;
    integer            a, b;
    reg signed [22:0]  acc;
    reg signed [22:0]  tv;

    always @* begin
        for (a = 0; a < NTAPS - 1; a = a + 1)
            tap[a] = ghp[(4*(NTAPS - 1 - a) - 1)*18 +: 18];
        tap[NTAPS-1] = in_g;
        msum = 23'd0;
        for (a = 0; a < NTAPS; a = a + 1) begin
            tv   = {{5{tap[a][17]}}, tap[a]};
            msum = msum + (tv[22] ? -tv : tv);
        end
        for (b = 0; b < 16; b = b + 1) begin
            acc = 23'sd0;
            for (a = 0; a < NTAPS; a = a + 1) begin
                tv  = {{5{tap[a][17]}}, tap[a]};
                acc = WNEG[b*NTAPS + a] ? acc - tv : acc + tv;
            end
            vec_c[b*23 +: 23] = acc;
        end
    end

    // --- RSSI window ------------------------------------------------------------
    reg [SIDE_W-1:0] mbuf [0:RSSI_WIN-1];
    reg [8:0]        mpos;
    reg              mfull;      // every window slot written since reset (slots read as zero until then)
    reg [16:0]       wsum;
    wire [16:0]      wsum_next = wsum + {{(17-SIDE_W){1'b0}}, in_mag} - (mfull ? {{(17-SIDE_W){1'b0}}, mbuf[mpos]} : 17'd0);

    // --- stage 1: vector --------------------------------------------------------
    reg                s1_valid;
    reg  [31:0]        s1_n;
    reg  [16*23-1:0]   s1_vec;
    reg  [22:0]        s1_mag;
    reg  [16:0]        s1_rsum;

    always @(posedge clk) begin
        s1_valid <= 1'b0;
        if (!rst_n) begin
            ghp  <= {HIST*18{1'b0}};
            nin  <= 32'd0;
            mpos <= 9'd0;
            wsum <= 17'd0;
            mfull <= 1'b0;
        end else if (in_valid) begin
            ghp  <= {ghp[(HIST-1)*18-1:0], in_g};
            nin  <= nin + 32'd1;
            mbuf[mpos] <= in_mag;
            mpos <= (mpos == RSSI_WIN - 1) ? 9'd0 : mpos + 9'd1;
            if (mpos == RSSI_WIN - 1) mfull <= 1'b1;
            wsum <= wsum_next;
            if (nin >= HIST) begin
                s1_valid <= 1'b1;
                s1_n     <= nin;
                s1_vec   <= vec_c;
                s1_mag   <= msum;
                s1_rsum  <= wsum_next;
            end
        end
    end

    // --- stage 2: argmax and accept --------------------------------------------
    reg  [3:0]         best_c;
    reg signed [22:0]  cb;
    integer            m;
    always @* begin
        best_c = 4'd0;
        cb     = s1_vec[22:0];
        for (m = 1; m < 16; m = m + 1)
            if ($signed(s1_vec[m*23 +: 23]) > cb) begin
                cb     = s1_vec[m*23 +: 23];
                best_c = m[3:0];
            end
    end

    wire signed [26:0] cb_x  = {{4{cb[22]}}, cb};
    wire signed [26:0] cb4   = cb_x <<< 2;
    wire signed [26:0] mag_x = {4'b0000, s1_mag};
    wire signed [26:0] mag3  = mag_x + (mag_x <<< 1);
    wire               ok_c  = (cb_x >= 27'sd126976) && (cb4 >= mag3);       // 4096 * 31

    always @(posedge clk) begin
        o_valid <= 1'b0;
        if (rst_n && s1_valid) begin
            o_valid <= 1'b1;
            o_n     <= s1_n;
            o_vec   <= s1_vec;
            o_best  <= best_c;
            o_ok    <= ok_c;
            o_rsum  <= s1_rsum;
        end
    end

endmodule
