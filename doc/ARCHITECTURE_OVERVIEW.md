# Architektur-Übersicht: Market Data Subscription Handling

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT (API Request)                        │
│  GET /options/AAPL/chain?expiry=2025-01-15&include_level2=true       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FASTAPI ROUTE LAYER                             │
│  routes_options.py                                                   │
│  ✅ include_level2 Query Parameter empfangen                         │
│  ✅ Documentation mit Fallback-Info                                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       SERVICE LAYER                                  │
│  options_service.OptionsService                                      │
│  ✅ include_level2 an Provider übergeben                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PROVIDER LAYER (IBKR)                             │
│  app/providers/ibkr.py                                               │
│                                                                       │
│  get_option_chain(symbol, expiry, include_level2)                    │
│  ├─ ✅ _ensure_connection()                                          │
│  ├─ 📊 include_level2? → _set_market_data_type(1)                   │
│  ├─ 📋 Contracts qualifizieren                                       │
│  └─ 📡 _get_tickers_snapshot(skip_on_error=True)                    │
│                                                                       │
│     ┌──────────────────────────────────────────────────────┐         │
│     │ _get_tickers_snapshot() - Fehlertolerante Snapshot  │         │
│     │                                                      │         │
│     │ Für jeden Contract:                                 │         │
│     │  try:                                               │         │
│     │    ticker = ib.reqMktData(contract)                │         │
│     │  catch Subscription Error:                         │         │
│     │    ├─ _handle_subscription_error() aufrufen       │         │
│     │    ├─ if skip_on_error: continue (skip)           │         │
│     │    └─ else: raise                                  │         │
│     │                                                      │         │
│     │ _handle_subscription_error()                        │         │
│     │  ├─ Fehler 10091 oder 'subscription' erkennen?    │         │
│     │  ├─ _subscription_errors.append({...})             │         │
│     │  ├─ logger.warning()                               │         │
│     │  └─ return fallback_on_subscription_error          │         │
│     └──────────────────────────────────────────────────────┘         │
│                                                                       │
│  📤 Return OptionChain (mit verfügbaren Daten)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      RESPONSE (200 OK)                               │
│  {                                                                   │
│    "data": {                                                         │
│      "underlying_symbol": "AAPL",                                    │
│      "options": [                                                    │
│        { "symbol": "AAPL 250115C00150000",                           │
│          "strike": 150.0,                                            │
│          "bid": 5.20,      ← Level 1 (immer vorhanden)              │
│          "ask": 5.30,      ← Level 1 (immer vorhanden)              │
│          ...                                                         │
│        }                                                             │
│      ]                                                               │
│    }                                                                 │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘

⚠️  LOG: Subscription error detected: Error 10091
    Contract: AAPL 150.0
    → Aber: Daten werden trotzdem zurückgegeben! ✅
```

## Fehler-Behandlung Flow

```
┌─────────────────────────┐
│  Daten anfordern        │
│  (include_level2=true)  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐       ┌──────────────────────────┐
│  Subscription vorhanden?├──YES──→ Level 2 Daten laden     │
│                         │        └────────┬─────────────────┘
└────────────┬────────────┘                  │
             │NO                            ▼
             ▼                     ┌────────────────────────┐
   ┌────────────────────┐         │   Fehler 10091?        │
   │ Level 1 laden      │         └────────┬───────────────┘
   └────────┬───────────┘                  │
            │                        YES ┌─┴──────┐ NO
            │                           ▼         ▼
            │                     ┌──────────┐  [Exception]
            │                     │Fallback? │
            │                     └────┬─────┘
            │                        YES│
            │                          ▼
            │                  ┌──────────────────┐
            │ ◄────────────────┤ Level 1 laden    │
            │                  │ (mit Warning)    │
            │                  └──────────────────┘
            │
            └─────────────────────┬──────────────────┐
                                  ▼                  ▼
                        ┌────────────────┐  ┌────────────────┐
                        │  Bid/Ask/Price │  │ Order Book     │
                        │  (Level 1)     │  │ (Level 2)      │
                        │  ✅ IMMER      │  │ 🔲 OPTIONAL    │
                        │  VORHANDEN     │  │ (mit Subsc.)   │
                        └────────────────┘  └────────────────┘
```

## Config Optionen

```
┌─────────────────────────────────────────────────────┐
│  app/config.py                                       │
│                                                      │
│  IBKR_MARKET_DATA_TYPE = 1  ← Live (beste Kompatib.)│
│      Optionen:                                       │
│      1 = Live       ✅ für Optionen                  │
│      2 = Frozen    ❓ gemischt                       │
│      3 = Delayed   ❌ für Optionen                   │
│      4 = Frozen    ❓ gemischt                       │
│                                                      │
│  IBKR_FALLBACK_ON_SUBSCRIPTION_ERROR = True          │
│      True  = Graceful Degradation ✅                │
│      False = Strict (Fehler werfen) ❌              │
└─────────────────────────────────────────────────────┘
```

## Daten Availability Matrix

```
┌──────────────────┬─────────────┬──────────────┬────────────┐
│ Data Type        │ Level 1     │ Level 2      │ Benötigte  │
│                  │ (Standard)  │ (Optional)   │ Subscription
├──────────────────┼─────────────┼──────────────┼────────────┤
│ Last Price       │ ✅          │ ✅           │ Level 1    │
│ Bid/Ask          │ ✅          │ ✅           │ Level 1    │
│ Volume           │ ✅          │ ✅           │ Level 1    │
│ Order Book Tiefe │ ❌          │ ✅           │ Level 2    │
│ Implied Vol.     │ ❌          │ ✅           │ Level 2    │
│ Greeks (Delta)   │ ❌          │ ✅           │ Level 2    │
└──────────────────┴─────────────┴──────────────┴────────────┘

Level 1 ist ausreichend für die meisten Use-Cases! ✅
Level 2 ist optional für erweiterte Analysen
```

## Request/Response Beispiele

### Scenario 1: Standard (Level 1, keine Subscription nötig)
```
REQUEST:
GET /options/AAPL/chain?expiry=2025-01-15

RESPONSE: 200 OK
{
  "data": {
    "options": [
      {
        "symbol": "AAPL 250115C00150000",
        "strike": 150.0,
        "bid": 5.20,
        "ask": 5.30,
        "volume": 1500,
        "type": "call"
      }
    ]
  }
}

✅ Keine Subscription nötig!
```

### Scenario 2: Mit Level 2 (mit Subscription)
```
REQUEST:
GET /options/AAPL/chain?expiry=2025-01-15&include_level2=true

RESPONSE: 200 OK (mit erweiterten Daten)
{
  "data": {
    "options": [
      {
        "symbol": "AAPL 250115C00150000",
        "bid": 5.20,
        "ask": 5.30,
        "implied_volatility": 0.25,    ← Level 2
        "delta": 0.65,                 ← Level 2
        "gamma": 0.05,                 ← Level 2
        "theta": -0.02,                ← Level 2
        "vega": 0.15                   ← Level 2
      }
    ]
  }
}

✅ Level 2 Subscription aktiviert!
```

### Scenario 3: Fehlertoleranz (ohne Level 2 Subscription)
```
REQUEST:
GET /options/AAPL/chain?expiry=2025-01-15&include_level2=true

LOG:
⚠️  WARNING: Subscription error detected: Error 10091

RESPONSE: 200 OK (mit Level 1 Fallback)
{
  "data": {
    "options": [
      {
        "symbol": "AAPL 250115C00150000",
        "bid": 5.20,
        "ask": 5.30,
        "implied_volatility": null,   ← Nicht verfügbar
        "delta": null,                ← Nicht verfügbar
        "gamma": null,                ← Nicht verfügbar
        "theta": null,                ← Nicht verfügbar
        "vega": null                  ← Nicht verfügbar
      }
    ]
  }
}

✅ Gracefully degraded zu Level 1!
```

## Komponenten-Übersicht

| Komponente | Änderung | Status |
|-----------|----------|--------|
| `app/config.py` | Market Data Type Config | ✅ Bereit |
| `app/providers/base.py` | Interface erweitert | ✅ Bereit |
| `app/providers/ibkr.py` | Error-Handling + Level 2 | ✅ Bereit |
| `app/services/options_service.py` | Parameter durchgereicht | ✅ Bereit |
| `app/api/routes_options.py` | Query-Parameter + Docs | ✅ Bereit |
| `tests/integration/test_ibkr.py` | Level 2 Tests | ✅ Bereit |
| Dokumentation | 3 neue Guides | ✅ Bereit |

---

**Status:** 🚀 Deployment-Ready
