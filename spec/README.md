# spec

Ratified specification (**revision 1**) and decision records. Ratification
scope, open items and the amendment rule are in
[0008](decisions/0008-ratification-and-amendment.md); the spec carries no
claim of qualification, certification or compliance.

| File | Contents |
|---|---|
| [target-spec.md](target-spec.md) | The parameter table (target / fallback / stretch, verification method, governing-spec section, simulated?) and the channel model. Siblings extend it. |
| [decisions/0001-phy-set.md](decisions/0001-phy-set.md) | PHY set |
| [decisions/0002-channel-model.md](decisions/0002-channel-model.md) | Channel model for error-rate claims |
| [decisions/0003-demod-architecture.md](decisions/0003-demod-architecture.md) | LE demodulator: coherent vs. non-coherent |
| [decisions/0004-shared-frontend-path.md](decisions/0004-shared-frontend-path.md) | One front-end sample interface serves both PHYs |
| [decisions/0005-tx-modulation-output.md](decisions/0005-tx-modulation-output.md) | TX modulation output is a signed frequency-deviation word |
| [decisions/0006-lower-mac-split.md](decisions/0006-lower-mac-split.md) | Lower-MAC hardware/software split |
| [decisions/0007-bit-exactness.md](decisions/0007-bit-exactness.md) | Bit-exactness: shared stimulus and golden traces, replayed by cocotb |
| [decisions/0008-ratification-and-amendment.md](decisions/0008-ratification-and-amendment.md) | Ratification scope, open items, amendment rule, changelog |
| [timing-and-area.md](timing-and-area.md) | Liberty corners, clock targets, digital latency `L_dig`, area budget |
| [frontend-interface.md](frontend-interface.md) | RX/TX signal tables, turnaround budget |
| [host-interface.md](host-interface.md) | Host interface (held until #15) |

Rules: cite specification section numbers only (never copy text or figures);
mark unchecked citations `unverified`; agents do not relax a ratified spec to
make results pass; changes go through a decision record. Decision records are
numbered in one sequence (0001–0008); this file is the only index.

## Traceability to parent #2

Each acceptance criterion and each "parameters to decide" item of #2, and where
it is answered.

| #2 item | Answered in |
|---|---|
| AC1: target spec, every parameter with target / fallback / stretch, method, section | [target-spec.md](target-spec.md) parameter table; timing rows in [timing-and-area.md](timing-and-area.md) |
| AC2: front-end interface as signal table | [frontend-interface.md](frontend-interface.md) §2–§4 |
| AC3: channel model defined | [target-spec.md](target-spec.md) "Channel model"; [0002](decisions/0002-channel-model.md) |
| AC4: hardware/software split fixed | [0006](decisions/0006-lower-mac-split.md); [host-interface.md](host-interface.md) |
| AC5: timing targets name liberty corners | [timing-and-area.md](timing-and-area.md) §1–§2 |
| AC6: no qualification/certification/compliance claim | Rule in [0008](decisions/0008-ratification-and-amendment.md); `grep -riE 'qualif|certif|complian' --include='*.md' .` outside the installed Loom tooling (`.loom`, `.claude`, `.agents`) yields only prohibitions (this file, `README.md`, `CLAUDE.md`) |
| Param: PHYs | [target-spec.md](target-spec.md) PHY set; [0001](decisions/0001-phy-set.md) |
| Param: RX front-end interface (rate, width, IF, AGC/RSSI, DC) | [frontend-interface.md](frontend-interface.md) §2; [0004](decisions/0004-shared-frontend-path.md) |
| Param: TX interface | [frontend-interface.md](frontend-interface.md) §3; [0005](decisions/0005-tx-modulation-output.md) |
| Param: demodulator performance, CFO/drift, timing drift | [target-spec.md](target-spec.md) demodulator, offset and timing tables; [0003](decisions/0003-demod-architecture.md) |
| Param: channel model | [target-spec.md](target-spec.md); [0002](decisions/0002-channel-model.md) |
| Param: lower MAC in hardware | [0006](decisions/0006-lower-mac-split.md) |
| Param: host interface | [host-interface.md](host-interface.md) |
| Param: timing and area | [timing-and-area.md](timing-and-area.md) |
| Open Q: shared interface for both PHYs | [0004](decisions/0004-shared-frontend-path.md) |
| Open Q: coherent vs non-coherent | [0003](decisions/0003-demod-architecture.md) (provisional default) |
| Open Q: synthesizer-settling budget | [frontend-interface.md](frontend-interface.md) §5; `L_dig` in [timing-and-area.md](timing-and-area.md) §3 |
| Open Q: how bit-exactness is enforced | [0007](decisions/0007-bit-exactness.md) |
