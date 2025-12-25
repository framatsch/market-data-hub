# OPRA Subscription with IBKR API - How To Guide

## Overview

This guide shows how to use your OPRA subscription with the IBKR API to get option bid/ask spreads and Greeks.

**Key Finding:** Type 2 (FROZEN) market data works perfectly with OPRA, giving you full option quotes including bid/ask and Greeks.

---

## Quick Start

### 1. Update Configuration

Choose one method:

**Option A: config.py**
```python
# app/config.py
IBKR_MARKET_DATA_TYPE: int = 2  # FROZEN with OPRA
```

**Option B: Environment Variable**
```bash
export IBKR_MARKET_DATA_TYPE=2
```

**Option C: .env File**
```bash
# .env
IBKR_MARKET_DATA_TYPE=2
```

### 2. Verify It Works

```bash
LOG_LEVEL=CRITICAL python test_type2_frozen.py
```

Expected output:
```
Option (AAPL Call 275, Jan 2026):
  Last:   ✅ $4.43
  Close:  ✅ $3.85
  Bid:    ✅ $4.45      ← OPRA provides this!
  Ask:    ✅ $4.55      ← OPRA provides this!

  Greeks available:
    IV:    0.1677575028766894
    Delta: 0.49492838778576026
```

---

## Understanding Market Data Types

| Feature | Type 1 (LIVE) | **Type 2 (FROZEN)** | Type 3 (DELAYED) |
|---------|---|---|---|
| Option Bid/Ask | ❌ | **✅** | ❌ |
| Greeks | ✅ | **✅** | ✅ |
| Price Data | ✅ | **✅** | ✅ |
| Delay | Real-time | **Frozen** | 15-20 min |
| Cost | Extra fee | **Free with OPRA** | Free |
| Recommended | ❌ | **✅ BEST** | ⚠️ Alternative |

### Type 2 (FROZEN) - What You Get

```
✅ Option Bid/Ask Spreads  (OPRA subscription)
✅ Option Prices           (Last/Close)
✅ Greeks                  (IV, Delta, Gamma, Vega, Theta)
✅ Fast Updates            (whenever market moves)
```

This is the **recommended solution** for options trading with your OPRA subscription.

### Type 3 (DELAYED) - Free Alternative

If you don't need bid/ask:

```
✅ Option Prices           (15-20 minute delay)
✅ Greeks                  (free!)
❌ Bid/Ask                (not available)
🎁 Cost                    (completely free - no subscription needed)
```

---

## How It Works

### Market Data Type 2 (FROZEN)

When you request Type 2:
1. IBKR returns the **last known Bid/Ask prices**
2. These update whenever the market updates them
3. During market hours, updates are frequent
4. Outside market hours, you get the last known values

### Why Not Type 1 (LIVE)?

We tested Type 1 and found:
- ❌ No Bid/Ask data available via API
- ❌ "API Market Data Access" setting doesn't exist for your account
- ❌ This is a limitation of IBKR API

Type 2 is the workaround that actually works!

---

## Testing Different Configurations

### Test Type 2 (FROZEN) - Recommended

```bash
IBKR_MARKET_DATA_TYPE=2 LOG_LEVEL=CRITICAL python test_type2_frozen.py
```

You should see:
- Option Bid/Ask prices ✅
- Greeks data ✅

### Test Type 3 (DELAYED) - Free Alternative

```bash
IBKR_MARKET_DATA_TYPE=3 LOG_LEVEL=CRITICAL python test_clean_prices.py
```

You should see:
- Option prices ✅
- Greeks data ✅
- No Bid/Ask ❌
- 15-20 min delay ⏱️

### Test Type 1 (LIVE) - For Reference

```bash
IBKR_MARKET_DATA_TYPE=1 LOG_LEVEL=CRITICAL python test_opra_simple.py
```

Result: No Bid/Ask data (doesn't work for your account)

---

## API Integration

Once configured, your application will automatically get:

### Stock Quotes
```python
quote = await provider.get_last_price("AAPL")
# Returns: price, bid (if available), ask (if available)
```

### Option Chains
```python
from datetime import date
chain = await provider.get_option_chain(
    "AAPL",
    date(2026, 1, 16),
    min_strike=270,
    max_strike=280
)
# Returns: options with bid/ask (Type 2) + Greeks
```

### Option Quotes
```python
quote = await provider.get_option_quote("AAPL", "AAPL  260116C00275000")
# Returns: price, bid/ask (Type 2), Greeks
```

All data includes the Greeks:
- `implied_volatility` - IV
- `delta` - Price sensitivity
- `gamma` - Delta sensitivity
- `vega` - Volatility sensitivity
- `theta` - Time decay

---

## Troubleshooting

### Problem: Still No Bid/Ask Data

**Check these in order:**

1. **Verify OPRA is active in TWS:**
   - Open TWS/Gateway
   - Account → Settings → Market Data Subscriptions
   - Look for "OPRA" or "Options Market Data"
   - Status should be: ✅ Activated or ✅ Waived

2. **Check configuration:**
   ```bash
   # Verify it's set to Type 2
   grep IBKR_MARKET_DATA_TYPE app/config.py
   grep IBKR_MARKET_DATA_TYPE .env
   ```

3. **Run the test:**
   ```bash
   LOG_LEVEL=INFO python test_type2_frozen.py 2>&1 | head -50
   ```

4. **Check during market hours:**
   - Frozen quotes only update during US market hours
   - Outside hours, you get the last known values

### Problem: Greeks Not Showing

The Greeks come from `modelGreeks` in IBKR's market data:
- Available with Type 2 and Type 3
- Shows theoretical values calculated by IBKR
- Not real-time like bid/ask but good for analysis

### Problem: Bid/Ask Show -1 or None

This means:
- ❌ No subscription for that data type
- ✅ Type 2 should fix this
- Check that OPRA is truly activated in TWS

---

## Performance Notes

### Type 2 vs Type 3

**Type 2 (FROZEN)** - Better:
- ✅ Faster data (updates whenever market moves)
- ✅ Bid/Ask spreads included
- ✅ Good for active trading

**Type 3 (DELAYED)** - Lighter:
- ✅ Lower bandwidth usage
- ✅ No Bid/Ask needed
- ✅ Good for analysis/research
- ⏱️ 15-20 minute delay

For options trading with Greeks, **Type 2 is recommended**.

---

## Real-World Example

Here's what you get with Type 2:

```python
import asyncio
from app.providers.ibkr import IBKRProvider
from datetime import date

async def get_options():
    provider = IBKRProvider()

    # Get current price
    quote = await provider.get_last_price("AAPL")
    print(f"AAPL: ${quote.price}")

    # Get ATM options
    chain = await provider.get_option_chain(
        "AAPL",
        date(2026, 1, 16),
        min_strike=270,
        max_strike=280
    )

    for opt in chain.options:
        if opt.type == "call":
            print(f"\nCall {opt.strike}:")
            print(f"  Price:    ${opt.price}")
            print(f"  Bid/Ask:  ${opt.bid} / ${opt.ask}")  # ✅ Works with Type 2
            print(f"  IV:       {opt.implied_volatility}")
            print(f"  Delta:    {opt.delta}")

asyncio.run(get_options())
```

Output:
```
AAPL: $273.81

Call 275.0:
  Price:    $3.85
  Bid/Ask:  $4.45 / $4.55     ← OPRA provides this!
  IV:       0.1677575028766894
  Delta:    0.49492838778576026
```

---

## FAQ

**Q: Can I use Type 1 instead?**
A: No, Type 1 doesn't work with OPRA for API access. Use Type 2.

**Q: What if OPRA expires/cancels?**
A: Fall back to Type 3 (DELAYED) - same Greeks, no bid/ask, but free.

**Q: Do frozen quotes update in real-time?**
A: Yes, during market hours. They update whenever the market updates them.

**Q: Can I switch between Type 2 and Type 3?**
A: Yes, just change `IBKR_MARKET_DATA_TYPE` and restart your application.

**Q: Is Type 2 slower than Type 1?**
A: Type 2 (frozen) and Type 1 (live) are similar speed. Type 3 (delayed) is slower due to 15-20 min delay.

**Q: Does my monthly commission waiver work with Type 2?**
A: Yes! OPRA is free when you trade $20+/month. Type 2 works with this waiver.

---

## Summary

✅ **Use Type 2 (FROZEN)** with your OPRA subscription
✅ You get **Option Bid/Ask + Greeks**
✅ Updates are **fast** (whenever market moves)
✅ Cost is **free** (covered by OPRA waiver)

That's it! 🎉
