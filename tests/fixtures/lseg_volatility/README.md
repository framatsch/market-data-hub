# Recorded LSEG volatility data

Copied from `tmp/lseg_iv_spike_out/`, captured on 2026-11-06 using
`refinitiv-data==1.6.2`. CSV contents are unchanged. Values are upstream
percentages, not hub fractions. Snapshot runs occurred at different times;
the R6 file supplies the separately recorded underlying/market metadata.

`P2b_hist_daily_fields__AAPLATMIV.U.csv` is the explicit-FID daily history
sample. `errors.json` contains unique entitlement messages extracted from
the spike reports, without tracebacks or local paths.
