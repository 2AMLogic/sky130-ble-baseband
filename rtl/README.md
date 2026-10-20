# rtl

Synthesizable RTL. `rtl/smoke/` holds a **placeholder** 8-bit LFSR
(`lfsr8.v`) that exists only to exercise the verification, lint and synthesis
flow; it is not part of the baseband and goes away once real RTL uses the same
flow. See `verification/README.md` for the flow.
