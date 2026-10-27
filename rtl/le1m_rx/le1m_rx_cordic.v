// LE 1M RX stage 2b: vectoring-mode CORDIC angle (model: cordic_angle).
// 12 iterations, one pipeline register per iteration, full turn = 2^16.
// x < 0 is folded by negating (x, y) and starting at half a turn; arithmetic
// shifts truncate toward minus infinity; the atan table is
// round(atan(2^-i) / 2pi * 2^16); an all-zero input forces the angle to 0; the
// 16-bit accumulator wraps modulo 2^16 as the model's final wrap does.
module le1m_rx_cordic #(
    parameter SIDE_W = 9
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                in_valid,
    input  wire signed [18:0]  in_x,
    input  wire signed [18:0]  in_y,
    input  wire [SIDE_W-1:0]   in_side,
    output wire                out_valid,
    output wire signed [15:0]  out_angle,
    output wire [SIDE_W-1:0]   out_side
);
    localparam XW = 21;   // |(x,y)| <= 185364, times the CORDIC gain 1.647, < 2^20

    function [15:0] atan_tab(input integer i);
        case (i)
            0:  atan_tab = 16'd8192;
            1:  atan_tab = 16'd4836;
            2:  atan_tab = 16'd2555;
            3:  atan_tab = 16'd1297;
            4:  atan_tab = 16'd651;
            5:  atan_tab = 16'd326;
            6:  atan_tab = 16'd163;
            7:  atan_tab = 16'd81;
            8:  atan_tab = 16'd41;
            9:  atan_tab = 16'd20;
            10: atan_tab = 16'd10;
            default: atan_tab = 16'd5;
        endcase
    endfunction

    reg signed [XW-1:0] sx [0:12];
    reg signed [XW-1:0] sy [0:12];
    reg        [15:0]   sa [0:12];
    reg                 sz [0:12];
    reg                 sv [0:12];
    reg [SIDE_W-1:0]    ss [0:12];

    wire signed [XW-1:0] fx = {{(XW-19){in_x[18]}}, in_x};
    wire signed [XW-1:0] fy = {{(XW-19){in_y[18]}}, in_y};

    // stage 0: fold
    always @(posedge clk) begin
        sv[0] <= 1'b0;
        if (rst_n && in_valid) begin
            sv[0] <= 1'b1;
            sx[0] <= in_x[18] ? -fx : fx;
            sy[0] <= in_x[18] ? -fy : fy;
            sa[0] <= in_x[18] ? 16'h8000 : 16'h0000;
            sz[0] <= (in_x == 19'sd0) && (in_y == 19'sd0);
            ss[0] <= in_side;
        end
    end

    genvar i;
    generate
        for (i = 0; i < 12; i = i + 1) begin : g_iter
            wire signed [XW-1:0] xs = sx[i] >>> i;
            wire signed [XW-1:0] ys = sy[i] >>> i;
            wire                 up = ~sy[i][XW-1];   // y >= 0
            always @(posedge clk) begin
                sv[i+1] <= rst_n & sv[i];
                sz[i+1] <= sz[i];
                ss[i+1] <= ss[i];
                sx[i+1] <= up ? sx[i] + ys : sx[i] - ys;
                sy[i+1] <= up ? sy[i] - xs : sy[i] + xs;
                sa[i+1] <= up ? sa[i] + atan_tab(i) : sa[i] - atan_tab(i);
            end
        end
    endgenerate

    assign out_valid = sv[12];
    assign out_angle = sz[12] ? 16'sd0 : $signed(sa[12]);
    assign out_side  = ss[12];
endmodule
