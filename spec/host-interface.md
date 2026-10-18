# Host interface

Status: proposed, for ratification under #9. Parent: #2. Split rationale:
`spec/decisions/0006-lower-mac-split.md`. This file gives widths and semantics at
outline level. A bit-level register map comes with the RTL.

Section citations in this file are unverified (see the citation-status note in
the decision record). Values in this file are proposals; area and clock
effects are assessed in sibling D (#9), not here.

## 1. Register bus

| Item | Decision |
|---|---|
| Protocol | AMBA APB4-style (PSEL, PENABLE, PWRITE, PADDR, PWDATA, PSTRB, PRDATA, PREADY, PSLVERR). Chosen for being simple, single-clock and widely supported; a host bridge is outside this block. |
| Data width | 32 bits |
| Address width | 12 bits, byte addressed (4 KiB window); word accesses, `PSTRB` honoured on writes |
| Clock | Core clock (32 MHz target, 16 MHz fallback). Single clock domain, so no synchronizers inside the block. |
| Wait states | `PREADY` is high in one access except FIFO-data reads, which never block (empty read returns 0 and sets `RX_UNDERFLOW`) |
| Errors | `PSLVERR` on access to an unmapped address or write to a read-only register |
| Reset | Asynchronous assert, synchronous release; all registers return the documented reset value, FIFOs empty, radio idle |

### Address map outline

| Offset | Block | Contents |
|---|---|---|
| 0x000 | Control / status | PHY select (LE 1M, 15.4), channel/frequency hint to front end, enable, TX-start and RX-start commands, state (idle, RX, TX, turnaround), abort |
| 0x040 | Interrupts | `INT_STATUS`, `INT_ENABLE`, `INT_RAW` (see section 3) |
| 0x080 | Timing | Turnaround override registers (default to spec values), ACK enable, trigger compare value and arm |
| 0x0C0 | Link config | LE access address, CRC init, whitening channel index, LE own address (48 bit + type bits); 15.4 PAN ID, short address, extended address (64 bit), frame-pending bit, promiscuous mode |
| 0x100 | FIFO windows | `TX_DATA`, `TX_LEVEL`, `RX_DATA`, `RX_LEVEL`, packet-descriptor registers (section 2) |
| 0x140 | Timestamp | Free-running counter read, per-event capture registers (section 4) |
| 0x180 | Front end | RSSI readback and the hooks defined in #7 |
| 0xFF0 | ID | Block identification and version, read-only |

## 2. FIFOs

| Item | TX FIFO | RX FIFO |
|---|---|---|
| Entry width | 8 bits (one octet) | 8 bits (one octet) |
| Depth | 288 octets (one maximum LE PDU of 257 octets plus margin; holds a 127-octet 15.4 PSDU with room to preload an ACK-class response) | 288 octets |
| Access | Write low byte of `TX_DATA` pushes one octet; bits 31:8 ignored | Read of `RX_DATA` pops one octet into bits 7:0 |
| Level | `TX_LEVEL`, 9 bits | `RX_LEVEL`, 9 bits |
| Contents | Payload octets only; header fields for the PHY are generated in hardware from a length register | Payload octets only; CRC/FCS is checked and not stored |
| Source of length | `TX_LENGTH` register (set by host before start) | Packet-descriptor FIFO |

Depth is a parameter. 288 is the starting proposal so that one maximum packet
fits; the area-based decision belongs to #9.

### Packet descriptor (RX)

A 4-entry descriptor FIFO holds one entry per received packet, in order:
length (9 bits), flags (CRC/FCS ok, truncated, address match, ACK sent, PHY),
RSSI (8 bits, from #7 hook), start-of-frame timestamp, end-of-frame timestamp.
Read through descriptor registers; a write to the pop register discards the
head. A fifth packet while four are held is dropped, as with data overflow.

### Overflow and underflow behaviour

| Condition | Behaviour |
|---|---|
| RX FIFO full during receive | Excess octets are discarded; the packet is marked truncated; the CRC/FCS result is not trusted for it (flag shows truncated, CRC-ok forced to 0); `RX_OVERFLOW` interrupt set. Older data is never overwritten. No ACK is sent for a truncated 15.4 frame. |
| Descriptor FIFO full at packet start | Packet ignored from the start; `RX_OVERFLOW` set. |
| TX start with fewer octets than `TX_LENGTH` | Start refused, `TX_ERROR` set, no emission. |
| TX FIFO runs empty mid-packet | Not reachable if the start check passes; if forced (e.g. a host reset of the FIFO), transmission is aborted, `TX_ERROR` set, modulator returns to idle. |
| RX read when empty | Returns 0, sets `RX_UNDERFLOW` (status only; not an interrupt by default). |
| TX write when full | Write ignored, `TX_OVERFLOW` set. |

## 3. Interrupts

One level-sensitive output `irq` (high when any enabled status bit is set).

| Bit | Name | Set when | Cleared by |
|---|---|---|---|
| 0 | `RX_SYNC` | Access address (LE) or SFD (15.4) detected | Write 1 to `INT_STATUS` bit |
| 1 | `RX_DONE_OK` | Packet received, CRC/FCS ok, passed filter, descriptor pushed | Write 1 |
| 2 | `RX_DONE_BAD` | Packet ended with CRC/FCS failure or filter reject (reject only if promiscuous capture is on) | Write 1 |
| 3 | `RX_OVERFLOW` | Section 2 conditions | Write 1 |
| 4 | `TX_DONE` | Last bit of transmitted packet emitted | Write 1 |
| 5 | `TX_ERROR` | Start refused or underflow | Write 1 |
| 6 | `ACK_SENT` | Automatic ACK emitted (15.4) | Write 1 |
| 7 | `ACK_TIMEOUT` | ACK-wait timer expired with no ACK (15.4) | Write 1 |
| 8 | `RESPONSE_SENT` | LE timed response emitted at T_IFS | Write 1 |
| 9 | `TRIGGER` | Timestamp trigger reached its compare value | Write 1 |

Semantics: `INT_STATUS` is the masked view of `INT_RAW`; `INT_ENABLE` masks
only the output. Raw bits are sticky and cleared by write-1-to-clear on
`INT_RAW`; clearing `INT_STATUS` clears the matching raw bit. An event that
arrives in the same cycle as a clear wins (the bit stays set), so no event is
lost. There is no read-to-clear, to avoid side effects on debug reads.

## 4. Timestamping

| Item | Decision |
|---|---|
| Reference clock | Core clock, divided down to a 1 MHz tick by a fixed counter (`CLK_PER_US` = 32 at 32 MHz, 16 at 16 MHz) |
| Counter | 32-bit tick count (wraps in about 71.6 minutes) with a sub-tick field of 5 bits counting core cycles inside the tick |
| Resolution | One core clock (31.25 ns at 32 MHz) via the sub-tick field; 1 µs from the tick field alone |
| Read | Reading the low word latches the high field, so the pair is coherent |
| Stamped events | RX sync detected (start of frame), RX end, TX start (first bit of preamble/SHR), TX end, trigger fire |
| Storage | RX start/end go into the packet descriptor (section 2); the most recent TX start/end and trigger fire sit in capture registers |
| Clock quality | The reference is the core clock; its accuracy versus the 2.4 GHz crystal is a system matter (the front end owns the crystal). Drift correction is host software. |
| Trigger | One compare register: when the counter equals it, start TX or RX (selected by command) with jitter of one core clock; this is the anchor for LE connection events and 15.4 IFS enforcement |

## 5. Edge notes and open items

- Whether the timed LE response needs a hardware SN/NESN patch is open
  (decision record R1).
- Register-level bit map is out of scope until RTL.
- Front-end signals, settling-time budget and digital-latency symbol: #7 and #9.
- No qualification, certification or compliance claim is made by this
  interface; it describes a digital block that implements the LE 1M physical
  layer and an 802.15.4 O-QPSK baseband.
