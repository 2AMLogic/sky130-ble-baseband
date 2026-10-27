// 802.15.4 O-QPSK RX stage 5: preamble run, SFD match (model: demodulate's run
// detect and _walk_to_sfd), streaming over the correlator results.
//
// SEARCH   a run of four accepted symbol-0 matches 128 correlator indices
//          apart (the model's `run`, from a 385-deep history of `zero`) starts
//          a candidate at the hit index h
// SETTLE   best symbol-0 correlation over h .. h+3 (first on ties) gives h2
// WALK     from h2, one accepted symbol per 128 indices: up to 16 further
//          zeros in all, then symbol 7, then symbol 10 (SFD A7 low nibble
//          first). Anything else is a failure at that index; a new candidate
//          may start from that same index on (the model's `floor`)
// FOUND    `found` is a combinational pulse in the cycle of the correlator
//          result at the SFD's last symbol; this block then stays quiet until
//          reset (one packet per capture, as the model).
//
// A capture that ends before any of this completes simply never raises
// `found`: that is the model's "no sync" outcome.
module oqpsk_rx_sync (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              c_valid,
    input  wire [3:0]        c_best,
    input  wire              c_ok,
    input  wire signed [22:0] c_corr0,     // correlator for symbol 0
    output wire              found
);
    localparam [1:0] S_SEARCH = 2'd0, S_SETTLE = 2'd1, S_WALK = 2'd2, S_FOUND = 2'd3;
    localparam [4:0] PREAMBLE_RUN = 5'd4, MAX_PREAMBLE_SYMBOLS = 5'd16;

    reg [1:0]  state;
    reg [383:0] zh;                 // zh[d] = `zero` at index i-1-d
    reg [7:0]  dly;                 // correlator results to skip before the next check
    reg [4:0]  zeros;
    reg        wstage;              // 0: expecting zero or symbol 7, 1: expecting symbol 10
    reg [1:0]  cand;                // candidates seen so far in SETTLE
    reg [1:0]  bestoff;
    reg signed [22:0] bestv;

    wire zero_now = c_ok && (c_best == 4'd0);
    wire run      = zero_now & zh[127] & zh[255] & zh[383];

    wire check = c_valid && (state == S_WALK) && (dly == 8'd0);
    wire fail  = check && (wstage ? !(c_ok && c_best == 4'd10)
                                  : !c_ok || (c_best == 4'd0 ? (zeros + 5'd1 > MAX_PREAMBLE_SYMBOLS)
                                                             : (c_best != 4'd7)));
    assign found = check && wstage && c_ok && (c_best == 4'd10);

    wire better = c_corr0 > bestv;

    always @(posedge clk) begin
        if (!rst_n) begin
            state   <= S_SEARCH;
            zh      <= {384{1'b0}};
            dly     <= 8'd0;
            zeros   <= 5'd0;
            wstage  <= 1'b0;
            cand    <= 2'd0;
            bestoff <= 2'd0;
            bestv   <= 23'sd0;
        end else if (c_valid) begin
            zh <= {zh[382:0], zero_now};
            case (state)
                S_SETTLE: begin
                    cand <= cand + 2'd1;
                    if (better) begin
                        bestv   <= c_corr0;
                        bestoff <= cand;
                    end
                    if (cand == 2'd3) begin
                        state  <= S_WALK;
                        wstage <= 1'b0;
                        zeros  <= PREAMBLE_RUN;
                        dly    <= 8'd124 + {6'd0, better ? cand : bestoff};
                    end
                end
                S_WALK: begin
                    if (dly != 8'd0) begin
                        dly <= dly - 8'd1;
                    end else if (found) begin
                        state <= S_FOUND;
                    end else if (fail) begin
                        state <= S_SEARCH;
                    end else if (!wstage && c_best == 4'd0) begin
                        zeros <= zeros + 5'd1;
                        dly   <= 8'd127;
                    end else begin          // symbol 7
                        wstage <= 1'b1;
                        dly    <= 8'd127;
                    end
                end
                default: ;
            endcase
            // a hit starts a candidate from SEARCH, or from the index where a walk just failed
            if (run && (state == S_SEARCH || fail)) begin
                state   <= S_SETTLE;
                cand    <= 2'd1;
                bestoff <= 2'd0;
                bestv   <= c_corr0;
            end
        end
    end
endmodule
