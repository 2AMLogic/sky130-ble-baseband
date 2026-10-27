// Interrupt and error status (spec/host-interface.md sec. 3).
//   INT_STATUS = INT_RAW & INT_ENABLE, irq = |INT_STATUS.
// Raw and error bits are sticky; an event in the same cycle as a clear wins.
// Write-1 on INT_RAW clears a raw bit regardless of enable; write-1 on INT_STATUS
// clears it only while the bit is enabled. ERR_STATUS never drives irq.
module host_irq (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [9:0]  ev,          // one-cycle event strobes, bit order = INT_RAW
    input  wire [1:0]  err_ev,      // [0] RX_UNDERFLOW, [1] TX_OVERFLOW
    input  wire [9:0]  raw_clr,     // W1C bits written to INT_RAW (byte lanes already applied)
    input  wire [9:0]  stat_clr,    // W1C bits written to INT_STATUS
    input  wire [1:0]  err_clr,     // W1C bits written to ERR_STATUS
    input  wire        en_we,       // write to INT_ENABLE
    input  wire [31:0] wd,          // write data
    input  wire [31:0] wmask,       // byte-lane mask from PSTRB
    output reg  [9:0]  int_raw,
    output reg  [9:0]  int_enable,
    output wire [9:0]  int_status,
    output reg  [1:0]  err_status,
    output wire        irq
);
    assign int_status = int_raw & int_enable;
    assign irq        = |int_status;

    wire [9:0] clr = raw_clr | (stat_clr & int_enable);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            int_raw    <= 10'd0;
            int_enable <= 10'd0;
            err_status <= 2'd0;
        end else begin
            int_raw    <= (int_raw & ~clr) | ev;
            err_status <= (err_status & ~err_clr) | err_ev;
            if (en_we) int_enable <= (int_enable & ~wmask[9:0]) | (wd[9:0] & wmask[9:0]);
        end
    end

    wire _unused = &{1'b0, wd[31:10], wmask[31:10]};
endmodule
