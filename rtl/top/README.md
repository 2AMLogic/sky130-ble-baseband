# rtl/top: baseband top level

`baseband_top` integrates the sub-blocks behind the pins of
[`spec/frontend-interface.md`](../../spec/frontend-interface.md) (RX table 2.2,
TX table 3.2, mode control 4) and the APB4 slave and `irq` of
[`spec/host-interface.md`](../../spec/host-interface.md) (1, 3), with the
names as the spec gives them. `host_top`'s lower-case ports and its `rst_n_in`
stay internal.

| Module | Implements |
|---|---|
| `baseband_top` | pin-for-pin top; wires the blocks; selects the PHY; `rx_flush`; RSSI hold |
| `bb_ctrl` | host-interface 1 `STATE`, frontend-interface 4 sequencing (`fe_*`, 3-clk `fe_ready` hold-off), TX start check of host-interface 2 |
| `bb_rx_adapt` | host-interface 2 RX FIFO / descriptor / overflow rows, 3 interrupts; decision 0006 rows 11, 13, 14 (frame fields into the filters) |
| `bb_tx_path` | host-interface 2 TX FIFO to `le1m_tx` / `oqpsk_tx`; the automatic ACK frame (0006 row 11) |
| `bb_timing_regs` | host-interface 1 address map, 0x080 Timing window |

## Choices the spec leaves open

None of these changes a ratified value; they are the integration decisions.

1. **Octet streams.** The receivers expose only trace taps. LE bits (kind 1) are
   assembled into octets; 15.4 octets (kind 7) are taken as they come. The RX
   FIFO gets the whole LE PDU (2 header octets plus payload, CRC dropped, same
   convention as `TX_LENGTH`) and the 15.4 PSDU without its FCS (two-octet delay
   line). The descriptor length is the number of octets pushed.
2. **Filter reject is dropped (operator ruling on #73).** The RX FIFO holds a
   packet's octets as provisional (`host_fifo` `HOLD`): they take space but are
   invisible to `RX_LEVEL`/`RX_DATA` until the packet ends. At `rx_end` the adapter
   commits them, or, for a CRC-good packet the address filter rejects, rolls the
   write pointer back to the packet start. A rejected packet leaves no octets and
   no descriptor, raises `RX_DONE_BAD`, and earns no ACK and no response. CRC-bad
   packets are still delivered with `CRC_OK` = 0. Consequence: `RX_LEVEL` grows
   when a packet ends, not while it arrives.
3. **LE access-address compare** is fed the configured address: the received one
   is not observable (the receiver syncs on the configured one).
4. **De-whitening** is on in the LE receiver (`cfg_whiten_ch`), as on air.
5. **One packet per RX start.** `RX_START` (or the trigger) resets the selected
   receiver and opens the front end; after `rx_end` the state returns to idle
   unless a timed response is scheduled (LE `RESP_EN`, 15.4 `ACK_EN`), when the
   front end switches to TX at `rx_end` so the synthesizer settles inside the
   turnaround. After a TX the state goes back to RX if an ACK wait (15.4) or a
   T_IFS window (LE, `RESP_EN`) is open. `rx_flush` is generated after 64 idle
   clk of the sample strobe.
6. **Descriptor flag `ACK_SENT`** means "an automatic ACK is scheduled" at push
   time; the ACK itself goes out 192 us later.
7. **0x080 Timing window** (`bb_timing_regs`): `TIMING_CTRL` (ACK_EN, RESP_EN,
   CRC_GATE), `TRIG_CMP`, `TRIG_CTRL` (arm, TX/RX mode, cancel), `TRIG_STATUS`.
   The window is decoded in the top; `host_top` is unchanged. The trigger has its
   own 1 us counter in `mac_trigger`, besides the one in `host_timestamp`.

## L_DIG_CYCLES

`make test-top` prints, at 32 MHz and simulated at RTL level, the end of the last
packet sample to `rx_end` and to the first `tx_valid` word:

| PHY | end of packet to `rx_end` | `rx_end` to first word (derived) | `L_DIG_CYCLES` set to |
|---|---|---|---|
| 15.4 | 34 clk | 7 clk | 41 |
| LE 1M | 133 clk | 6 clk | 139 |

With these values the first word lands within 1 clk of the 192 us / 150 us
deadline in the bench (it asserts +/-8 and +/-16 clk; the LE air end is known to
about +/-4 clk from the channel model). The `section 3` bounds (1024 and 320 clk)
were not what the design does: at the bounds the 15.4 ACK started 983 clk
(30.7 us) early. The numbers are for the noiseless one-packet stimulus of the
bench, 32 MHz only; the 16 MHz fallback is not measured, so there `LE_L_DIG_CYCLES`
and `OQ_L_DIG_CYCLES` must be overridden with the bounds. They exclude the front
end's group delay `D_fe`.

## Not done

- Turnaround override registers (host-interface 0x080): `mac_timer` and its users
  take their counts as parameters, so a register cannot change them without
  editing those blocks (out of scope here).
- AGC (`agc_gain` mid-scale, `agc_gain_we` never fires; `agc_hold` follows sync);
  `rssi` is the saturated linear value, as in the receivers.
- Back-to-back packets without a new `RX_START`; LE 2M and coded PHY.
- Hardware SN/NESN patching of the LE response (open item R1 in 0006).
- Any error-rate claim: the bench is noiseless and checks function and latency.
