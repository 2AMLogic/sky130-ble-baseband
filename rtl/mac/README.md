# rtl/mac: lower-MAC hardware deadlines

Implements the hardware rows of
[decision 0006](../../spec/decisions/0006-lower-mac-split.md) for issue #51:

| Module | Function (0006 row) |
|---|---|
| `mac_timer` | Interval timer core, one instance per deadline |
| `mac_le_resp` | LE T_IFS timer and timed-response trigger (8, 12) |
| `mac_ack_ctrl` | 15.4 turnaround timer and automatic ACK (9, 11) |
| `mac_ackwait` | 15.4 ACK-wait timer, cancelled on ACK reception (9) |
| `mac_trigger` | Timestamp counter and compare trigger (10) |
| `mac_addr_filter_154` | 15.4 PAN / short / extended / broadcast / promiscuous filter (13) |
| `mac_le_filter` | LE own-address (SCAN_REQ, CONNECT_IND) and AA compare (14) |

Registers are module ports; the APB map is #50 and top integration is #52.
Strobe outputs map to the host events `ACK_SENT` (`ack_tx_req`), `ACK_TIMEOUT`
(`ev_ack_timeout`), `RESPONSE_SENT` (`resp_tx_req`), `TRIGGER` (`trig_fire`).

## Timing

Deadline modules fire the TX command `deadline - L_DIG_CYCLES` cycles after the
end-of-packet decision (`timing-and-area.md` section 3). Counts are parameters;
the 16 MHz fallback values are the halved counts (`verification/mac/run_mac.py`
overrides them). All numbers are **simulated at RTL level, on cycle counts**;
no µs figure is claimed without a named clock.

Limits of the evidence: the benches model `L_rx` and `L_tx` at their section 3
bounds, so "end of packet to first `tx_valid` equals the deadline" holds by
construction of `L_DIG_CYCLES`. The measured quantity of this block is
`rx_end` to the TX command (5120 / 4480 cycles at 32 MHz, jitter 0). If the
integrated design's real `L_rx + L_tx` is below the bound, the 15.4 ACK starts
early; #52 must set `L_DIG_CYCLES` from the measured latency.

## Assumptions to check (spec clauses are unverified, see 0006)

- 15.4: short address `0xFFFE`/`0xFFFF` never match as unicast; no automatic
  ACK in promiscuous mode; frames with no destination are accepted and left to
  software.
- Frame-pending is sampled at `rx_end`, not at ACK transmit time.
- Turnaround override registers (host-interface 0x080) are not implemented here.
