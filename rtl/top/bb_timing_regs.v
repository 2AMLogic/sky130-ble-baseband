// Timing register window 0x080..0x0BF (spec/host-interface.md section 1 address
// map, "Timing"): ACK / response enables and the trigger compare and arm. Lives
// beside host_top because that block reserves the window and ignores it
// (rtl/host/REGMAP.md "0x080 Timing"). The turnaround override registers named in
// the outline are NOT implemented: the lower-MAC timers take their counts as
// elaboration parameters, not as ports (rtl/top/README.md, "Not done").
//
//   0x080 TIMING_CTRL  RW  [0] ACK_EN (15.4 auto-ACK), [1] RESP_EN (LE timed
//                           response), [2] CRC_GATE (response needs CRC ok), reset 4
//   0x084 TRIG_CMP     RW  [31:0] compare value, 1 us ticks (mac_trigger)
//   0x088 TRIG_CTRL    WO  [0] ARM, [1] MODE_TX (1 = start TX, 0 = start RX; used by
//                           an ARM in the same write), [2] CANCEL; one-cycle pulses
//   0x08C TRIG_STATUS  RO  [0] armed
// Other addresses in the window read 0 and ignore writes. PREADY is always 1.
module bb_timing_regs (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sel,            // PSEL & window decode
    input  wire        penable,
    input  wire        pwrite,
    input  wire [11:0] paddr,
    input  wire [31:0] pwdata,
    input  wire [3:0]  pstrb,
    output reg  [31:0] prdata,

    output reg         ack_en,
    output reg         resp_en,
    output reg         crc_gate,
    output reg  [31:0] trig_cmp,
    output reg         trig_arm,
    output reg         trig_cancel,
    output reg         trig_mode_tx,
    input  wire        trig_armed
);
    wire _unused = &{1'b0, paddr[11:6], paddr[1:0]};
    wire wr = sel & penable & pwrite;
    always @* begin
        case (paddr[5:2])
            4'd0: prdata = {29'd0, crc_gate, resp_en, ack_en};
            4'd1: prdata = trig_cmp;
            4'd3: prdata = {31'd0, trig_armed};
            default: prdata = 32'd0;
        endcase
    end
    always @(posedge clk) begin
        trig_arm <= 1'b0;
        trig_cancel <= 1'b0;
        if (!rst_n) begin
            ack_en <= 1'b0; resp_en <= 1'b0; crc_gate <= 1'b1;
            trig_cmp <= 32'd0; trig_mode_tx <= 1'b0;
        end else if (wr) begin
            case (paddr[5:2])
                4'd0: if (pstrb[0]) begin ack_en <= pwdata[0]; resp_en <= pwdata[1]; crc_gate <= pwdata[2]; end
                4'd1: begin
                    if (pstrb[0]) trig_cmp[7:0]   <= pwdata[7:0];
                    if (pstrb[1]) trig_cmp[15:8]  <= pwdata[15:8];
                    if (pstrb[2]) trig_cmp[23:16] <= pwdata[23:16];
                    if (pstrb[3]) trig_cmp[31:24] <= pwdata[31:24];
                end
                4'd2: if (pstrb[0]) begin
                    trig_mode_tx <= pwdata[1];
                    trig_arm     <= pwdata[0];
                    trig_cancel  <= pwdata[2];
                end
                default: ;
            endcase
        end
    end
endmodule
