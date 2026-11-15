# RTL file list of baseband_top: the one place lint, synthesis and every bench
# read from. One repo-relative path per line.
#
# The `# block:` comments group those paths into the per-block source lists the
# block lints and the block benches read, through the single parser in
# verification/rtl_sources.py (`make lint`, verification/*/run_*.py). Both
# markers sit at column 0 and are ordinary comments to `verilator -f`,
# flow/synth/synth.tcl and flow/synth/profile.sh:
#
#   # block: <name>     every path below belongs to block <name>, in this order
#   # reuse: <path> ...  also put paths already declared above, in another
#                        block, into this block's list at this position --
#                        without listing them again for baseband_top
#
# So adding, renaming or moving an RTL file is one edit, here.

# block: host
rtl/host/host_fifo.v
rtl/host/host_desc_fifo.v
rtl/host/host_irq.v
rtl/host/host_timestamp.v
rtl/host/host_regs.v
rtl/host/host_top.v
# block: le1m_tx
rtl/le1m_tx/le1m_whiten.v
rtl/le1m_tx/le1m_crc24.v
rtl/le1m_tx/le1m_frame.v
rtl/le1m_tx/le1m_gauss.v
rtl/le1m_tx/le1m_tx.v
# block: le1m_rx
rtl/le1m_rx/le1m_rx_fir.v
rtl/le1m_rx/le1m_rx_disc.v
rtl/le1m_rx/le1m_rx_cordic.v
rtl/le1m_rx/le1m_rx_integ.v
rtl/le1m_rx/le1m_rx_sync.v
rtl/le1m_rx/le1m_rx_pkt.v
rtl/le1m_rx/le1m_rx.v
# block: oqpsk_tx
rtl/oqpsk/oqpsk_tx.v
# block: oqpsk_rx
rtl/oqpsk/oqpsk_rx_fir.v
# oqpsk_rx reuses two LE 1M RX stages unchanged (the model shares
# le1m_rx.discriminate), so they are in its list but not re-declared:
# reuse: rtl/le1m_rx/le1m_rx_disc.v rtl/le1m_rx/le1m_rx_cordic.v
rtl/oqpsk/oqpsk_rx_integ.v
rtl/oqpsk/oqpsk_rx_corr.v
rtl/oqpsk/oqpsk_rx_sync.v
rtl/oqpsk/oqpsk_rx_pkt.v
rtl/oqpsk/oqpsk_rx.v
# block: mac
rtl/mac/mac_timer.v
rtl/mac/mac_trigger.v
rtl/mac/mac_ack_ctrl.v
rtl/mac/mac_ackwait.v
rtl/mac/mac_le_resp.v
rtl/mac/mac_addr_filter_154.v
rtl/mac/mac_le_filter.v
# block: top
rtl/top/bb_timing_regs.v
rtl/top/bb_rx_adapt.v
rtl/top/bb_tx_path.v
rtl/top/bb_ctrl.v
rtl/top/baseband_top.v
