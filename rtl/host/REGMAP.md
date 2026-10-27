# Host interface register map

Bit-level map for `rtl/host/`. Section numbers (§) refer to
[`spec/host-interface.md`](../../spec/host-interface.md), ratified revision 1,
which is not edited here. The testbench is `verification/host/` (`make host-test`).

Conventions (§1): 32-bit data, 12-bit byte address, word-aligned accesses, `PSTRB`
honoured per byte lane on writes, `PREADY` always 1. `PSLVERR` (access phase) on an
unmapped or unaligned address and on a write to a read-only register; such a write
has no effect. Reads of write-only registers return 0 without error. Reset:
asynchronous assert, synchronous release (two-flop release inside `host_top`); every
register returns its reset value, FIFOs are empty. Access types: RW, RO, WO,
W1C (write 1 to clear).

## 0x000 Control / status (§1 address map)

| Offset | Name | Type | Bits | Reset | Notes |
|---|---|---|---|---|---|
| 0x000 | `CTRL` | RW | [0] `ENABLE`, [1] `PHY` (0 LE 1M, 1 15.4), [14:8] `CHAN` (channel hint to front end) | 0 | other bits read 0, ignored |
| 0x004 | `CMD` | WO | [0] `TX_START`, [1] `RX_START`, [2] `ABORT`, [3] `TX_FIFO_RESET`, [4] `RX_FIFO_RESET` | – | each 1 bit gives a one-cycle pulse the cycle after the write. `RX_FIFO_RESET` also empties the descriptor FIFO |
| 0x008 | `STATE` | RO | [2:0] 0 idle, 1 RX, 2 TX, 3 turnaround | 0 | input port `state_i` driven by the MAC |

## 0x040 Interrupts and errors (§3, §2 overflow table)

`INT_RAW` / `INT_ENABLE` / `INT_STATUS` bit n:

| Bit | Name | Bit | Name |
|---|---|---|---|
| 0 | `RX_SYNC` | 5 | `TX_ERROR` |
| 1 | `RX_DONE_OK` | 6 | `ACK_SENT` |
| 2 | `RX_DONE_BAD` | 7 | `ACK_TIMEOUT` |
| 3 | `RX_OVERFLOW` | 8 | `RESPONSE_SENT` |
| 4 | `TX_DONE` | 9 | `TRIGGER` |

| Offset | Name | Type | Notes |
|---|---|---|---|
| 0x040 | `INT_RAW` | W1C [9:0] | sticky; write 1 clears the bit enabled or not |
| 0x044 | `INT_ENABLE` | RW [9:0] | reset 0 |
| 0x048 | `INT_STATUS` | RO view, W1C [9:0] | `INT_RAW & INT_ENABLE`; write 1 clears the raw bit only if enabled |
| 0x04C | `ERR_STATUS` | W1C [1:0] | [0] `RX_UNDERFLOW`, [1] `TX_OVERFLOW`; sticky, status only, no `irq` |

`irq = |INT_STATUS`. An event in the same cycle as a clear wins. No read-to-clear.
`RX_OVERFLOW` is raised by the external `rx_overflow` strobe, by a refused RX FIFO
push, and by a refused descriptor push.

## 0x080 Timing (outside this block)

0x080..0x0BF is a **reserved window**: reads 0, writes are ignored, no `PSLVERR`.
The turnaround, ACK-enable and trigger registers belong to the lower-MAC work and
are wired at top level integration; this block neither stores nor exports them.

## 0x0C0 Link configuration (§1 address map)

Plain RW registers, exported as ports for the MAC/PHY. Reset 0.

| Offset | Name | Bits | Port |
|---|---|---|---|
| 0x0C0 | `ACCESS_ADDR` | [31:0] | `cfg_access_addr` |
| 0x0C4 | `CRC_INIT` | [23:0] | `cfg_crc_init` |
| 0x0C8 | `WHITEN_CH` | [5:0] | `cfg_whiten_ch` |
| 0x0CC | `OWN_ADDR_LO` | [31:0] | `cfg_own_addr[31:0]` |
| 0x0D0 | `OWN_ADDR_HI` | [15:0] address, [17:16] type bits | `cfg_own_addr[47:32]`, `cfg_own_addr_type` |
| 0x0D4 | `PAN_ID` | [15:0] | `cfg_pan_id` |
| 0x0D8 | `SHORT_ADDR` | [15:0] | `cfg_short_addr` |
| 0x0DC | `EXT_ADDR_LO` | [31:0] | `cfg_ext_addr[31:0]` |
| 0x0E0 | `EXT_ADDR_HI` | [31:0] | `cfg_ext_addr[63:32]` |
| 0x0E4 | `FILT_CFG` | [0] `FRAME_PENDING`, [1] `PROMISCUOUS` | `cfg_frame_pending`, `cfg_promiscuous` |

## 0x100 FIFO windows (§2)

| Offset | Name | Type | Notes |
|---|---|---|---|
| 0x100 | `TX_DATA` | WO | `PSTRB[0]`=1: pushes `PWDATA[7:0]`; bits 31:8 ignored. Push while full is refused and sets `TX_OVERFLOW` |
| 0x104 | `TX_LENGTH` | RW [8:0] | exported as `tx_length`; the start check (§2 table) is MAC-side |
| 0x108 | `TX_LEVEL` | RO [8:0] | octets held |
| 0x10C | `RX_DATA` | RO [7:0] | the read pops one octet; empty read returns 0 and sets `RX_UNDERFLOW` |
| 0x110 | `RX_LEVEL` | RO [8:0] | |
| 0x114 | `DESC_COUNT` | RO [2:0] | descriptors held, 0..4 |
| 0x118 | `DESC_INFO` | RO | head descriptor: [8:0] length, [16] `CRC_OK`, [17] `TRUNCATED`, [18] `ADDR_MATCH`, [19] `ACK_SENT`, [20] `PHY` |
| 0x11C | `DESC_RSSI` | RO [7:0] | `fe_rssi` sampled at descriptor push |
| 0x120 | `DESC_TS_START` | RO | start-of-frame tick |
| 0x124 | `DESC_TS_END` | RO | end-of-frame tick |
| 0x128 | `DESC_TS_SUB` | RO | [4:0] start sub-tick, [12:8] end sub-tick |
| 0x12C | `DESC_POP` | WO | any write with `PSTRB[0]`=1 discards the head; empty is ignored |

Head registers read 0 when no descriptor is held. FIFO depth is the `FIFO_DEPTH`
parameter (default 288, at most 511); the descriptor FIFO is 4 deep.

## 0x140 Timestamp (§4)

| Offset | Name | Type | Notes |
|---|---|---|---|
| 0x140 | `TS_TICK` | RO | free-running 1 us tick; the read latches the sub-tick |
| 0x144 | `TS_SUB` | RO [4:0] | sub-tick as latched by the last `TS_TICK` read |
| 0x148 / 0x14C | `TX_START_TICK` / `_SUB` | RO | last `tx_start` |
| 0x150 / 0x154 | `TX_END_TICK` / `_SUB` | RO | last `tx_done` |
| 0x158 / 0x15C | `TRIG_TICK` / `_SUB` | RO | last `trigger` |

Sub-tick counts core cycles 0..`CLK_PER_US`-1 (parameter; 32 at 32 MHz, 16 at
16 MHz). A capture holds `{tick, sub}` of the cycle in which the strobe is high.
RX start and end captures go into the descriptor.

## 0x180 Front end (§1; hooks of `spec/frontend-interface.md` §2.2)

| Offset | Name | Type | Notes |
|---|---|---|---|
| 0x180 | `RSSI` | RO [7:0] | live `fe_rssi` |
| 0x184 | `FE_STATUS` | RO [0] | `fe_agc_settled` |

## 0xFF0 ID (§1)

| Offset | Name | Type | Value |
|---|---|---|---|
| 0xFF0 | `ID` | RO | 0x48494631 |
| 0xFF4 | `VERSION` | RO | 1 (host-interface revision 1) |

## Changes against the ratified outline

The outline is at register-block level; these are bit-level choices it did not
fix. None changes a ratified value or meaning, so none is an amendment.

1. Register offsets inside each block, field positions, and the `ID` / `VERSION`
   values are chosen here (§5 says the bit map arrives with the RTL).
2. `CMD` is a write-only pulse register and `STATE` an input-driven read-only
   register; the outline names the commands and states, not their encoding.
3. The descriptor registers (0x114..0x12C) and the `DESC_TS_*` split of tick and
   sub-tick are an elaboration of "descriptor registers" and "pop register" (§2).
4. Descriptor RSSI and timestamps are taken inside the block (`fe_rssi` at push,
   timestamp captures of `rx_sync` and `rx_end`), not supplied by the MAC. The MAC
   must push a descriptor at least one cycle after `rx_end`.
5. Timestamp pair coherence (§4 "reading the low word latches the high field"):
   the 32-bit tick is the word read first, and it latches the 5-bit sub-tick.
6. A read of a write-only register returns 0 without `PSLVERR`; a misaligned
   address is treated as unmapped.
7. The 0x080 Timing block is a reserved, ignored window (see above), because its
   behaviour is outside this block. The trigger compare value is therefore not
   stored here; only the `trigger` event strobe (capture and `TRIGGER` interrupt)
   is.
8. `PSTRB[0]` must be set for `TX_DATA` pushes and `DESC_POP`/`CMD` actions.
