# 0006 — Lower-MAC hardware/software split

Status: proposed, for ratification under #9. Parent: #2. Sibling interface
documents: `spec/host-interface.md` (this change); the front-end interface
and synthesizer-settling budget are owned by #7 and are only referenced here.

## Citation status

"LE" below means the LE Uncoded 1M PHY and link layer as described in the
Bluetooth Core Specification, Vol 6 Part B. "15.4" means the IEEE 802.15.4
2.4 GHz O-QPSK PHY and MAC. Section numbers are cited only; no specification
text is reproduced.

**Every section number in this record was written from memory. No copy of
either specification was available to the author, so none has been checked.
All are unverified** and must be checked before ratification (#9). Edition
differences in numbering are likely, especially for 802.15.4 (2011 vs. 2015
numbering differ). Where a clause could not be named at all, the table says
"clause unidentified".

## Decision

Hardware holds a function when a real-time deadline shorter than reliable
host-software latency applies (anything tied to a symbol or a turnaround
interval), or when it is a bit-serial operation at the symbol rate. Everything
else is host software. Area is the tiebreaker for functions with no deadline.

Deadlines are stated at the air interface (end of last received bit to start of
first transmitted bit). The digital latency inside the block, and the
front-end ready budget, are separate: the timer fires the TX command early
by those amounts (symbols `L_dig` from #9 and the budget from #7). That
arithmetic is not restated here.

Cycle counts assume the 32 MHz target clock (31.25 ns/cycle); at the 16 MHz
fallback they halve.

## Split table

| # | Function | PHY | Placement | Governing section (unverified) | Reason |
|---|---|---|---|---|---|
| 1 | Preamble and access-address correlation | LE | **HW** | Vol 6 Part B §2.1.1 preamble, §2.1.2 access address | Runs on the raw bit stream at 1 Msym/s; there is no host-visible sample stream to correlate in software. |
| 2 | SFD detection (preamble + SFD, chip correlation) | 15.4 | **HW** | PHY clause for the O-QPSK SHR (clause unidentified; the O-QPSK PHY is clause 10 in 2011, 12 in 2015) | Same: chip-rate operation at 2 Mchip/s. |
| 3 | CRC-24 generate/check | LE | **HW** | Vol 6 Part B §3.1.1 (CRC generation), initial value rules in §3.1.1 | Bit-serial at 1 Mb/s, and the result gates the T_IFS response. Per-connection init value is a register. |
| 4 | 16-bit FCS generate/check | 15.4 | **HW** | MAC frame-format clause, FCS field (§7.2.x in 2015, §5.2.1.9 in 2011; unverified) | Gates the acknowledgement deadline (row 11). |
| 5 | Data whitening / de-whitening | LE | **HW** | Vol 6 Part B §3.2 | Bit-serial, seeded from the channel index; trivial area, no value in software. Not used by 15.4. |
| 6 | Framing: LE (preamble choice, AA, header/length parse, CRC append) | LE | **HW** | Vol 6 Part B §2.1, §2.3 / §2.4 (PDU headers) | Hardware must know the length from the header to end the packet on time. |
| 7 | Framing: 15.4 (SHR, PHR length, PSDU, FCS) | 15.4 | **HW** | PPDU format clause (clause unidentified), PHR frame length | Same. |
| 8 | LE T_IFS turnaround timer | LE | **HW** | Vol 6 Part B §4.1.1 (inter frame space) | 150 µs +/- 2 µs. See deadline table. |
| 9 | 15.4 turnaround / ack-wait timers | 15.4 | **HW** | aTurnaroundTime (PHY constants clause); macAckWaitDuration (MAC PIB clause) | 192 µs and 864 µs. See deadline table. |
| 10 | Timestamped trigger (start RX/TX at counter value) | both | **HW** | LE connection-event anchor timing, Vol 6 Part B §4.5.x; 15.4 IFS rules (macSIFSPeriod / macLIFSPeriod) | Host cannot start a radio to microsecond accuracy; a compare trigger can. The IFS and anchor *policy* stays in software. |
| 11 | Automatic acknowledgement (15.4 ACK frame) | 15.4 | **HW** | MAC acknowledgement clause (§6.7.4 in 2015; unverified) | Must start 12 symbols (192 µs) after the frame; no software round trip fits. |
| 12 | LE timed response (transmit a pre-loaded packet at T_IFS) | LE | **HW timer, SW content** | Vol 6 Part B §4.1.1, §4.5.9 (SN/NESN acknowledgement) | The timer is hardware; SN/NESN/MD bits and the payload are prepared by the host before the response is needed (see risk R1). |
| 13 | Address filtering: 15.4 (PAN ID, short, extended, broadcast, promiscuous) | 15.4 | **HW** | MAC reception-and-rejection clause (§6.7.2 in 2015; unverified) | It decides whether row 11 acknowledges, inside 192 µs. |
| 14 | Address filtering: LE own-address compare on SCAN_REQ / CONNECT_IND, and on-air AA match | LE | **HW** (own address and AA only) | Vol 6 Part B §2.3 (advertising PDUs), §4.3 (device filtering) | SCAN_RSP must follow SCAN_REQ by T_IFS, so the "is it addressed to me" decision is hardware. |
| 15 | LE accept list, resolving-list / privacy resolution | LE | **SW** | Vol 6 Part B §4.3 (accept list); privacy in Vol 6 Part B §1.x (clause unidentified) | No deadline in hardware; flexible size. The host decides after the packet (it may drop a response, not make one). |
| 16 | Encryption and MIC (LE and 15.4 security) | both | **SW** (outside this block) | Vol 6 Part E; 15.4 security clause (clause unidentified) | Out of scope for the first tape-out. Encrypted payload passes through as ciphertext. Risk R2. |
| 17 | Connection state machine, channel selection, hop schedule, parameter update | LE | **SW** | Vol 6 Part B §4.5 | Host timescale (ms); uses row 10 triggers. |
| 18 | CSMA-CA, backoff, retransmission, association, MAC command handling, indirect queues | 15.4 | **SW** | MAC CSMA-CA and transmission clauses (§6.2.5 in 2015; unverified) | Host timescale. CCA energy value comes from the RSSI hook in #7. |
| 19 | Upper link layer and protocol stacks | both | **SW** | n/a | Host software by project scope; no stack is named. |

## Hardware-resident deadlines

Each timer states the interval, the spec section, and the cycle budget.

| Timer | Interval | Tolerance | Cycles @ 32 MHz | Governing section (unverified) | Measured from / to |
|---|---|---|---|---|---|
| LE T_IFS | 150 µs | +/- 2 µs | 4800 (+/- 64) | Vol 6 Part B §4.1.1 | End of last bit of received packet (or own transmitted packet) to start of first bit (preamble) of the next |
| 15.4 turnaround (ACK start) | 12 symbols = 192 µs (16 µs/symbol) | start no earlier than the constant (treated as exact; unverified) | 6144 | aTurnaroundTime, PHY constants clause; ACK timing in MAC acknowledgement clause (§6.7.4 in 2015) | End of last symbol of the received frame to start of the ACK SHR |
| 15.4 ACK wait | 54 symbols = 864 µs | upper bound: timeout fires at or after | 27648 | macAckWaitDuration, MAC PIB clause (§8.4.2 in 2015) | End of transmitted frame to expiry; cancelled on ACK reception |
| Timestamp trigger | 1 µs resolution, 1 core clock jitter | 1 cycle | 32 | n/a (implementation) | Counter compare to TX/RX start command |

Notes on the table: the 54-symbol value is derived from other 15.4 constants
(unit backoff 20 + turnaround 12 + SHR 10 + 6 octets x 2 symbols), which
agrees with the quoted figure; it is unverified in either form. IFS minima
(macSIFSPeriod 12 symbols, macLIFSPeriod 40 symbols) are enforced by the host
through row 10 and are not separate hardware timers. The synthesizer settling
budget, and its ready strobe, are a front-end requirement in #7.

## Risks and deliberate limits

- **R1, LE response contents.** The 150 µs window leaves no time for the host
  to react to the received header. The host must preload the response
  (including SN/NESN) assuming the common case. If the received SN/NESN make
  that assumption wrong, the host cannot repair it in time. Options for #9
  (to ratify, not decided here): hardware SN/NESN patch of the preloaded
  header, or a documented loss of that exchange. Hardware transmits only if
  the CRC check passed (configurable), so a bad CRC never triggers a response.
- **R2, security.** No hardware AES. A link that needs encryption works only
  if the host can finish MIC work outside the T_IFS window; this restricts the
  usable feature set and is a deliberate scope choice.
- **R3, 15.4 frame-pending bit.** The ACK frame-pending bit cannot be looked up
  in 192 µs. It is a register set by the host ahead of time (default 0).
- **R4, LE 2M and coded PHY.** Not a driver. Timers are parameterized by PHY,
  but nothing here is sized for them (README: stretch only).

## Alternatives rejected

- Everything but CRC/whitening in software: fails 150 µs and 192 µs.
- Hardware accept list and privacy resolution: area, with no deadline benefit.
- Hardware AES-CCM: area and scope; revisit after the target closes.
