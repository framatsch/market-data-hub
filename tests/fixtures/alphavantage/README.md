# Alpha Vantage fixtures

Captured with a free key on 17 November 2026 by
`tmp/alphavantage_spike.py`. The API key is not included.

- `cal_3m.csv` and `cal_12m.csv`: 30 unmodified rows each from the
  market-wide earnings calendar. The selection includes all observed release
  windows, empty estimates, dot-notation share classes and preferred shares
  (`JPM-PD`, `KEY-PL`) which the provider must filter out.
- `earn_AAPL.json`, `earn_BRK-B.json`: complete quarterly and annual history,
  including Alpha Vantage's string `None` values.
- `earn_BRK.B.json`, `earn_SPY.json`, `earn_UNKNOWN.json`: the empty objects
  returned for unsupported share-class notation, ETFs and unknown tickers.
- `daily_compact_AAPL.json`, `daily_compact_SPY.json`: the complete compact
  window of 100 daily bars.
- `weekly_AAPL.json`: full weekly history, including the running week and the
  unadjusted August 2020 split.
- `quote_AAPL.json`: an end-of-day global quote with its latest trading day.
- `daily_full_AAPL.json`, `daily_adj_AAPL.json`: the distinct HTTP-200 notices
  for a premium parameter and a premium endpoint.
- `burst_limit.json`: HTTP-200 burst throttle captured by
  `tmp/alphavantage_limit_probe.py` on the same day. It asks for one request
  per second but also mentions the daily limit and premium endpoints; these
  words alone must not be mistaken for daily exhaustion or missing entitlement.

These are recorded responses, not current dates or prices. Tests should freeze
their clock or use explicit ranges rather than expecting fixture dates to move.
