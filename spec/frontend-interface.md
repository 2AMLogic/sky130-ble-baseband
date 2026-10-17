# Front-end interface: RX/TX signal tables and turnaround budget

Status: DRAFT, pending ratification with [target spec](target-spec.md)
(parent #2; that file lands with sibling A, so the link is dangling until
then). Issue #7.

This document specifies the **digital interface** between this baseband and
an external RF front end. It does not design any RF, ADC, DAC or synthesizer
block; everything here is a requirement the front end must meet or a signal
the baseband provides. Behaviour is described by reference to the LE 1M
physical layer of the Bluetooth Core Specification and the IEEE 802.15.4
2.4 GHz O-QPSK physical layer. No compliance, qualification or certification
is claimed.

**Citation status.** Section numbers below were written from memory and could
not be checked against the specifications in this session. Every one is
marked *unverified* and must be checked before this document is ratified.
No specification text is reproduced.

## 1. Conventions

- Direction is from the baseband's point of view (`in` = from front end).
- `clk` is the single baseband clock: 32 MHz target, 16 MHz fallback (README
  target table). All interface signals are synchronous to `clk`; any
  sample-clock-domain crossing is the front end's (or a wrapper's) job and
  is out of scope here.
- `rst_n` is the baseband's active-low reset. "Reset" below is the value
  while `rst_n` is low and the first cycle after.
- Two operating points: **target** 8 Msps (one `rx_valid` per 4 `clk`
  cycles at 32 MHz) and **fallback** 4 Msps (one per 8 `clk` cycles at
  32 MHz). TX words follow the same grid.

## 2. RX path (front end to baseband)

### 2.1 Requirements on the sample stream

| Item | Target | Fallback | Notes |
|---|---|---|---|
| Sample rate | 8 Msps complex | 4 Msps complex | Average rate; see jitter below |
| Samples per LE 1M symbol | 8 | 4 | LE 1M is 1 Msym/s (Core Vol 6 Pt A, 2; *unverified*) |
| Samples per 802.15.4 chip | 4 | 2 | 2 Mchip/s at 2.4 GHz (802.15.4 O-QPSK PHY clause; *unverified*) |
| Sample width | 8-bit signed per component (I and Q) | same | Two's complement, mid-scale = 0 |
| Spectral position | Complex baseband, channel centre at 0 Hz | same | See IF below |
| Strobe jitter | `rx_valid` may be irregular by at most +/-1 `clk` cycle about the nominal grid | same | Models sample-clock drift handling; drift in ppm is a channel-model parameter (sibling A) |
| Back-pressure | none | none | Baseband must accept every sample |

**IF.** The front end delivers **zero-IF complex baseband**: it performs the
image-rejecting down-conversion and any analog channel filtering, and the
wanted channel is centred at 0 Hz up to carrier-frequency offset. Low-IF is
not supported at this interface (the baseband would need an image-reject
mixer it does not have). Residual frequency offset is handled by the
baseband and is a channel-model parameter, not an interface parameter.

**DC offset.** The front end shall null static DC to within 8 LSB (of a
+/-127 range) at either component; the baseband performs residual DC removal
(a configurable high-pass/mean tracker), which is part of the reference
receiver, not of this interface.

### 2.2 RX signal table

| Name | Dir | Width | Clock domain | Rate | Timing / handshake | Reset |
|---|---|---|---|---|---|---|
| `rx_i` | in | 8 (signed) | `clk` | 8 / 4 Msps | Valid only when `rx_valid`=1 | 0 |
| `rx_q` | in | 8 (signed) | `clk` | 8 / 4 Msps | Valid only when `rx_valid`=1 | 0 |
| `rx_valid` | in | 1 | `clk` | 8 / 4 MHz average | One-cycle pulse per sample; no ready/back-pressure | 0 |
| `rx_sat` | in | 1 | `clk` | with sample | Sampled with `rx_valid`; 1 = ADC/front-end saturation on this sample | 0 |
| `agc_gain` | out | 6 | `clk` | event | Requested gain index, higher = more gain; stable while `agc_gain_we`=0 | mid-scale (32) |
| `agc_gain_we` | out | 1 | `clk` | event | One-cycle pulse; front end latches `agc_gain` | 0 |
| `agc_settled` | in | 1 | `clk` | event | Level; deasserts within 2 `clk` of an `agc_gain_we`, reasserts when the new gain is stable in the sample stream | 1 |
| `agc_hold` | out | 1 | `clk` | level | 1 = front end shall not change gain autonomously (asserted from sync detect to end of packet) | 0 |
| `rssi_valid` | out | 1 | `clk` | per packet | One-cycle pulse when `rssi` is final for the packet | 0 |
| `rssi` | out | 8 | `clk` | per packet | Digital RSSI estimate in 1 dB steps, referenced to gain index in force; valid with `rssi_valid`, held until next packet | 0 |

**AGC ownership.** The baseband owns the gain loop policy (it knows packet
timing, so it can freeze gain after sync via `agc_hold`); the front end owns
gain *application* and must apply a gain request within 16 `clk` cycles
(0.5 us at 32 MHz), reporting completion with `agc_settled`. RSSI is
computed digitally from the I/Q magnitude plus the gain index; the front
end provides no analog RSSI. `rx_sat` lets the baseband back the gain off
on clipping.

## 3. TX path (baseband to front end)

### 3.1 Modulation output

The baseband emits a **signed frequency-deviation word** (decision record
[0002](decisions/0002-tx-modulation-output.md)). The front end maps it onto
its modulator (direct VCO, two-point or fractional-N); how it does so is
not specified here.

| Item | Target | Fallback |
|---|---|---|
| Word rate | 8 Msps | 4 Msps |
| Word width | 8-bit signed | same |
| LSB weight | 7.8125 kHz (8 MHz / 1024) | same (weight does not change with rate) |
| LE 1M nominal deviation | +/-32 LSB (+/-250 kHz) | same |
| 802.15.4 O-QPSK (half-sine) deviation | +/-64 LSB (+/-500 kHz) | same |
| Range | +/-127 LSB (+/-992 kHz) | same |

Both deviations are nominal values from the PHY descriptions (LE 1M
modulation index 0.5, Core Vol 6 Pt A, 3; *unverified*; 802.15.4 O-QPSK with
half-sine shaping viewed as constant-envelope MSK, deviation = chip rate / 4;
O-QPSK modulation clause, *unverified*). Gaussian filtering for LE is done in
the baseband, so the word is already shaped.

### 3.2 TX signal table

| Name | Dir | Width | Clock domain | Rate | Timing / handshake | Reset |
|---|---|---|---|---|---|---|
| `tx_dev` | out | 8 (signed) | `clk` | 8 / 4 Msps | Valid only when `tx_valid`=1; 0 when idle | 0 |
| `tx_valid` | out | 1 | `clk` | 8 / 4 MHz average | One-cycle pulse per word; no back-pressure; front end must not require retransmission | 0 |
| `tx_active` | out | 1 | `clk` | level | 1 from first word to last word + 1 sample; front end may gate PA ramp on it | 0 |

## 4. Mode control and turnaround handshake

| Name | Dir | Width | Clock domain | Rate | Timing / handshake | Reset |
|---|---|---|---|---|---|---|
| `fe_rx_en` | out | 1 | `clk` | level | Requests RX mode; mutually exclusive with `fe_tx_en` | 0 |
| `fe_tx_en` | out | 1 | `clk` | level | Requests TX mode; mutually exclusive with `fe_rx_en` | 0 |
| `fe_chan` | out | 7 | `clk` | event | Channel index per active PHY; stable while `fe_chan_we`=0 | 0 |
| `fe_chan_we` | out | 1 | `clk` | event | One-cycle pulse latches `fe_chan`; front end deasserts `fe_ready` within 2 `clk` | 0 |
| `fe_phy` | out | 1 | `clk` | level | 0 = LE 1M, 1 = 802.15.4; selects channel mapping only; sample interface is identical | 0 |
| `fe_ready` | in | 1 | `clk` | level | 1 = synthesizer settled on requested channel and chain is in the requested mode (RX or TX); deasserts within 2 `clk` of any change of `fe_rx_en`, `fe_tx_en` or `fe_chan_we` | 0 |

`fe_ready` is a level, not a strobe, so the baseband may sample it at any
time. With both `fe_rx_en` and `fe_tx_en` low the front end may power down
and `fe_ready` is 0.

## 5. Turnaround budget (requirement on the front end)

The synthesizer settling time is outside this repository. The baseband
assumes a maximum, derived below, and the front end must meet it.

### 5.1 Symbols

| Symbol | Meaning | Value / owner |
|---|---|---|
| `T_IFS` | LE inter-frame space, receive-to-transmit and transmit-to-receive | 150 us (Core Vol 6 Pt B, 4.1.1; *unverified*; tolerance per same section, *unverified*) |
| `T_TA` | 802.15.4 aTurnaroundTime | 12 symbol periods; symbol = 16 us at 2.4 GHz O-QPSK, so 192 us (802.15.4 PHY constants, MAC constants clauses; *unverified*) |
| `L_dig` | Digital latency: last on-air bit received to the TX decision, plus TX decision to the first `tx_valid` word | **Symbol; resolved by sibling D (#9)** |
| `D_fe` | Front-end group delay, RX chain plus TX chain (antenna to `rx_valid` plus `tx_valid` to antenna) | Front end |
| `T_settle` | Maximum time from `fe_tx_en`/`fe_rx_en` change to `fe_ready`=1 | Requirement derived here |
| `M` | Margin | 10 % of the governing interval, floor 2 us (draft; ratify in #1) |

`L_dig` is the sum of the RX-side detection latency (from the last bit
at the antenna to the baseband knowing the packet ended) and the TX-side
latency (from TX decision to the first word on `tx_dev`). Its value is
**not chosen here**.

### 5.2 Arithmetic

Mode switch is the only front-end action in the turnaround interval, so:

```
T_settle  <=  T_gov - L_dig - D_fe - M
```

where `T_gov` is the governing interval of the PHY in use.

| PHY | `T_gov` | `M` | Budget |
|---|---|---|---|
| LE 1M (RX to TX, TX to RX) | `T_IFS` = 150 us | 15 us | `T_settle <= 135 us - L_dig - D_fe` |
| 802.15.4 | `T_TA` = 192 us | 19.2 us | `T_settle <= 172.8 us - L_dig - D_fe` |

LE is the binding case. As a worked illustration only (not a requirement):
if sibling D sets `L_dig` = 10 us and the front end has `D_fe` = 5 us, then
`T_settle <= 120 us`.

The front end must state its own `D_fe` and `T_settle` in its datasheet; this
spec is satisfied when `T_settle + L_dig + D_fe + M <= T_gov` closes for the
binding PHY.

## 6. Decisions referenced

- [0001: shared RX/TX interface for both PHYs](decisions/0001-shared-frontend-path.md)
- [0002: TX modulation output is a frequency-deviation word](decisions/0002-tx-modulation-output.md)
