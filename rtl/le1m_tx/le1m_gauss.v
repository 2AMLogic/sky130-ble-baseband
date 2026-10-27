// LE 1M Gaussian pulse shaper: 33-tap FIR at 8 Msps over an NRZ (+1/-1)
// sequence, integer arithmetic only. Bit-exact with gaussian_shape() in
// sim/model/le1m_tx.py: taps are GAUSS_TAPS (copied, not re-derived),
// round half up at TAP_SHIFT = 10, saturate to int8. A position that is
// before the start or past the end of the input counts as 0 (`shv` clear),
// so the filter starts from a zero state and drains back to zero.
module le1m_gauss (
    input  wire             clk,
    input  wire             rst_n,   // active-low synchronous reset
    input  wire             clr,     // forget all history (new packet)
    input  wire             shift,   // take one input sample
    input  wire             din,     // NRZ sample: 1 = +1, 0 = -1
    input  wire             dvalid,  // 0 = the sample is zero (outside the packet)
    output wire signed [7:0] dev     // FIR output for the history as of the last `shift`
);
    localparam integer NTAPS = 33;

    reg [NTAPS-1:0] sh;   // sh[k]  = sign of the sample k slots ago
    reg [NTAPS-1:0] shv;  // shv[k] = that sample is inside the packet

    function integer tap(input integer k);
        case (k)
            7:       tap = 1;
            8:       tap = 5;
            9:       tap = 26;
            10:      tap = 112;
            11:      tap = 382;
            12:      tap = 1040;
            13:      tap = 2266;
            14:      tap = 3952;
            15:      tap = 5517;
            16:      tap = 6166;
            17:      tap = 5517;
            18:      tap = 3952;
            19:      tap = 2266;
            20:      tap = 1040;
            21:      tap = 382;
            22:      tap = 112;
            23:      tap = 26;
            24:      tap = 5;
            25:      tap = 1;
            default: tap = 0;
        endcase
    endfunction

    integer k;
    integer acc;
    integer w;
    always @* begin
        acc = 0;
        for (k = 0; k < NTAPS; k = k + 1)
            if (shv[k])
                acc = acc + (sh[k] ? tap(k) : -tap(k));
        w = (acc + 512) >>> 10;
    end

    wire [7:0] wlo = w[7:0];
    assign dev = (w > 127) ? 8'sd127 : (w < -128) ? -8'sd128 : wlo;

    always @(posedge clk) begin
        if (!rst_n || clr) begin
            sh  <= {NTAPS{1'b0}};
            shv <= {NTAPS{1'b0}};
        end else if (shift) begin
            sh  <= {sh[NTAPS-2:0], din};
            shv <= {shv[NTAPS-2:0], dvalid};
        end
    end
endmodule
