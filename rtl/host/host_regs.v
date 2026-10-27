// APB4 slave and register decode (spec/host-interface.md sec. 1; bit map in rtl/host/REGMAP.md).
// Single-clock, PREADY always 1. PSLVERR in the access phase for an unmapped or
// unaligned address, or a write to a read-only register; such a write has no effect.
// Writes honour PSTRB per byte lane. Registers only decode and hold configuration:
// FIFOs, interrupt state and timestamps live in sibling modules (host_top wires them).
module host_regs (
    input  wire        clk,
    input  wire        rst_n,

    // APB4 slave
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [11:0] paddr,
    input  wire [31:0] pwdata,
    input  wire [3:0]  pstrb,
    output reg  [31:0] prdata,
    output wire        pready,
    output wire        pslverr,

    // 0x000 control / status
    output reg         ctrl_enable,
    output reg         ctrl_phy,        // 0 = LE 1M, 1 = 802.15.4
    output reg  [6:0]  ctrl_chan,
    output reg         cmd_tx_start,    // one-cycle pulses, the cycle after the CMD write
    output reg         cmd_rx_start,
    output reg         cmd_abort,
    output reg         cmd_tx_flush,
    output reg         cmd_rx_flush,
    input  wire [2:0]  state_i,         // 0 idle, 1 RX, 2 TX, 3 turnaround

    // 0x040 interrupts / errors (host_irq)
    input  wire [9:0]  int_raw,
    input  wire [9:0]  int_enable,
    input  wire [9:0]  int_status,
    input  wire [1:0]  err_status,
    output wire [9:0]  irq_raw_clr,
    output wire [9:0]  irq_stat_clr,
    output wire [1:0]  irq_err_clr,
    output wire        irq_en_we,
    output wire [31:0] wd,
    output wire [31:0] wmask,

    // 0x0C0 link configuration
    output reg  [31:0] cfg_access_addr,
    output reg  [23:0] cfg_crc_init,
    output reg  [5:0]  cfg_whiten_ch,
    output reg  [47:0] cfg_own_addr,
    output reg  [1:0]  cfg_own_addr_type,
    output reg  [15:0] cfg_pan_id,
    output reg  [15:0] cfg_short_addr,
    output reg  [63:0] cfg_ext_addr,
    output reg         cfg_frame_pending,
    output reg         cfg_promiscuous,

    // 0x100 FIFO windows
    output wire        tx_push,
    output wire [7:0]  tx_wdata,
    output reg  [8:0]  tx_length,
    input  wire [8:0]  tx_level,
    output wire        rx_pop,
    input  wire [7:0]  rx_rdata,
    input  wire [8:0]  rx_level,
    input  wire [2:0]  desc_count,
    input  wire [8:0]  desc_len,
    input  wire [4:0]  desc_flags,
    input  wire [7:0]  desc_rssi,
    input  wire [36:0] desc_ts_start,
    input  wire [36:0] desc_ts_end,
    output wire        desc_pop,

    // 0x140 timestamp
    input  wire [31:0] ts_tick,
    input  wire [4:0]  ts_sub_latched,
    output wire        ts_rd_tick,
    input  wire [36:0] cap_tx_start,
    input  wire [36:0] cap_tx_end,
    input  wire [36:0] cap_trigger,

    // 0x180 front end
    input  wire [7:0]  fe_rssi,
    input  wire        fe_agc_settled
);
    localparam [31:0] ID_VALUE      = 32'h4849_4631;  // ASCII "HIF1"
    localparam [31:0] VERSION_VALUE = 32'h0000_0001;  // host-interface revision 1

    assign pready = 1'b1;

    wire acc = psel & penable;
    assign wmask = {{8{pstrb[3]}}, {8{pstrb[2]}}, {8{pstrb[1]}}, {8{pstrb[0]}}};
    assign wd    = pwdata & wmask;

    // ---- address decode: mapped / writable / read data ---------------------------------
    reg         mapped, writable;
    reg  [31:0] rdata;

    always @* begin
        mapped   = 1'b0;
        writable = 1'b0;
        rdata    = 32'd0;
        if (paddr[1:0] == 2'b00) begin
            case (paddr)
                12'h000: begin mapped = 1'b1; writable = 1'b1;
                    rdata = {17'd0, ctrl_chan, 6'd0, ctrl_phy, ctrl_enable}; end
                12'h004: begin mapped = 1'b1; writable = 1'b1; end
                12'h008: begin mapped = 1'b1; rdata = {29'd0, state_i}; end

                12'h040: begin mapped = 1'b1; writable = 1'b1; rdata = {22'd0, int_raw}; end
                12'h044: begin mapped = 1'b1; writable = 1'b1; rdata = {22'd0, int_enable}; end
                12'h048: begin mapped = 1'b1; writable = 1'b1; rdata = {22'd0, int_status}; end
                12'h04C: begin mapped = 1'b1; writable = 1'b1; rdata = {30'd0, err_status}; end

                12'h0C0: begin mapped = 1'b1; writable = 1'b1; rdata = cfg_access_addr; end
                12'h0C4: begin mapped = 1'b1; writable = 1'b1; rdata = {8'd0, cfg_crc_init}; end
                12'h0C8: begin mapped = 1'b1; writable = 1'b1; rdata = {26'd0, cfg_whiten_ch}; end
                12'h0CC: begin mapped = 1'b1; writable = 1'b1; rdata = cfg_own_addr[31:0]; end
                12'h0D0: begin mapped = 1'b1; writable = 1'b1;
                    rdata = {14'd0, cfg_own_addr_type, cfg_own_addr[47:32]}; end
                12'h0D4: begin mapped = 1'b1; writable = 1'b1; rdata = {16'd0, cfg_pan_id}; end
                12'h0D8: begin mapped = 1'b1; writable = 1'b1; rdata = {16'd0, cfg_short_addr}; end
                12'h0DC: begin mapped = 1'b1; writable = 1'b1; rdata = cfg_ext_addr[31:0]; end
                12'h0E0: begin mapped = 1'b1; writable = 1'b1; rdata = cfg_ext_addr[63:32]; end
                12'h0E4: begin mapped = 1'b1; writable = 1'b1;
                    rdata = {30'd0, cfg_promiscuous, cfg_frame_pending}; end

                12'h100: begin mapped = 1'b1; writable = 1'b1; end
                12'h104: begin mapped = 1'b1; writable = 1'b1; rdata = {23'd0, tx_length}; end
                12'h108: begin mapped = 1'b1; rdata = {23'd0, tx_level}; end
                12'h10C: begin mapped = 1'b1; rdata = {24'd0, rx_rdata}; end
                12'h110: begin mapped = 1'b1; rdata = {23'd0, rx_level}; end
                12'h114: begin mapped = 1'b1; rdata = {29'd0, desc_count}; end
                12'h118: begin mapped = 1'b1; rdata = {11'd0, desc_flags, 7'd0, desc_len}; end
                12'h11C: begin mapped = 1'b1; rdata = {24'd0, desc_rssi}; end
                12'h120: begin mapped = 1'b1; rdata = desc_ts_start[36:5]; end
                12'h124: begin mapped = 1'b1; rdata = desc_ts_end[36:5]; end
                12'h128: begin mapped = 1'b1;
                    rdata = {19'd0, desc_ts_end[4:0], 3'd0, desc_ts_start[4:0]}; end
                12'h12C: begin mapped = 1'b1; writable = 1'b1; end

                12'h140: begin mapped = 1'b1; rdata = ts_tick; end
                12'h144: begin mapped = 1'b1; rdata = {27'd0, ts_sub_latched}; end
                12'h148: begin mapped = 1'b1; rdata = cap_tx_start[36:5]; end
                12'h14C: begin mapped = 1'b1; rdata = {27'd0, cap_tx_start[4:0]}; end
                12'h150: begin mapped = 1'b1; rdata = cap_tx_end[36:5]; end
                12'h154: begin mapped = 1'b1; rdata = {27'd0, cap_tx_end[4:0]}; end
                12'h158: begin mapped = 1'b1; rdata = cap_trigger[36:5]; end
                12'h15C: begin mapped = 1'b1; rdata = {27'd0, cap_trigger[4:0]}; end

                12'h180: begin mapped = 1'b1; rdata = {24'd0, fe_rssi}; end
                12'h184: begin mapped = 1'b1; rdata = {31'd0, fe_agc_settled}; end

                12'hFF0: begin mapped = 1'b1; rdata = ID_VALUE; end
                12'hFF4: begin mapped = 1'b1; rdata = VERSION_VALUE; end
                default: begin
                    // 0x080..0x0BF: Timing block, reserved here (reads 0, writes ignored)
                    if (paddr[11:6] == 6'b000010) begin mapped = 1'b1; writable = 1'b1; end
                end
            endcase
        end
    end

    assign pslverr = acc & (~mapped | (pwrite & ~writable));

    wire wok = acc & pwrite & ~pslverr;
    wire rok = acc & ~pwrite & ~pslverr;

    always @* prdata = (psel & ~pwrite) ? rdata : 32'd0;

    // ---- strobes to sibling modules ---------------------------------------------------
    assign irq_raw_clr  = (wok && (paddr == 12'h040)) ? wd[9:0] : 10'd0;
    assign irq_stat_clr = (wok && (paddr == 12'h048)) ? wd[9:0] : 10'd0;
    assign irq_err_clr  = (wok && (paddr == 12'h04C)) ? wd[1:0] : 2'd0;
    assign irq_en_we    = wok && (paddr == 12'h044);

    assign tx_push    = wok && (paddr == 12'h100) && pstrb[0];
    assign tx_wdata   = pwdata[7:0];
    assign rx_pop     = rok && (paddr == 12'h10C);
    assign desc_pop   = wok && (paddr == 12'h12C) && pstrb[0];
    assign ts_rd_tick = rok && (paddr == 12'h140);

    // ---- configuration registers --------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_enable       <= 1'b0;
            ctrl_phy          <= 1'b0;
            ctrl_chan         <= 7'd0;
            cmd_tx_start      <= 1'b0;
            cmd_rx_start      <= 1'b0;
            cmd_abort         <= 1'b0;
            cmd_tx_flush      <= 1'b0;
            cmd_rx_flush      <= 1'b0;
            cfg_access_addr   <= 32'd0;
            cfg_crc_init      <= 24'd0;
            cfg_whiten_ch     <= 6'd0;
            cfg_own_addr      <= 48'd0;
            cfg_own_addr_type <= 2'd0;
            cfg_pan_id        <= 16'd0;
            cfg_short_addr    <= 16'd0;
            cfg_ext_addr      <= 64'd0;
            cfg_frame_pending <= 1'b0;
            cfg_promiscuous   <= 1'b0;
            tx_length         <= 9'd0;
        end else begin
            cmd_tx_start <= wok && (paddr == 12'h004) && pstrb[0] && pwdata[0];
            cmd_rx_start <= wok && (paddr == 12'h004) && pstrb[0] && pwdata[1];
            cmd_abort    <= wok && (paddr == 12'h004) && pstrb[0] && pwdata[2];
            cmd_tx_flush <= wok && (paddr == 12'h004) && pstrb[0] && pwdata[3];
            cmd_rx_flush <= wok && (paddr == 12'h004) && pstrb[0] && pwdata[4];
            if (wok) begin
                case (paddr)
                    12'h000: begin
                        if (pstrb[0]) begin ctrl_enable <= pwdata[0]; ctrl_phy <= pwdata[1]; end
                        if (pstrb[1]) ctrl_chan <= pwdata[14:8];
                    end
                    12'h0C0: cfg_access_addr <= (cfg_access_addr & ~wmask) | wd;
                    12'h0C4: cfg_crc_init <= (cfg_crc_init & ~wmask[23:0]) | wd[23:0];
                    12'h0C8: cfg_whiten_ch <= (cfg_whiten_ch & ~wmask[5:0]) | wd[5:0];
                    12'h0CC: cfg_own_addr[31:0] <= (cfg_own_addr[31:0] & ~wmask) | wd;
                    12'h0D0: begin
                        cfg_own_addr[47:32] <= (cfg_own_addr[47:32] & ~wmask[15:0]) | wd[15:0];
                        cfg_own_addr_type   <= (cfg_own_addr_type & ~wmask[17:16]) | wd[17:16];
                    end
                    12'h0D4: cfg_pan_id <= (cfg_pan_id & ~wmask[15:0]) | wd[15:0];
                    12'h0D8: cfg_short_addr <= (cfg_short_addr & ~wmask[15:0]) | wd[15:0];
                    12'h0DC: cfg_ext_addr[31:0] <= (cfg_ext_addr[31:0] & ~wmask) | wd;
                    12'h0E0: cfg_ext_addr[63:32] <= (cfg_ext_addr[63:32] & ~wmask) | wd;
                    12'h0E4: begin
                        if (pstrb[0]) begin
                            cfg_frame_pending <= pwdata[0];
                            cfg_promiscuous   <= pwdata[1];
                        end
                    end
                    12'h104: tx_length <= (tx_length & ~wmask[8:0]) | wd[8:0];
                    default: ;
                endcase
            end
        end
    end

    wire _unused = &{1'b0, pwdata[31:15], wmask[31:18]};
endmodule
