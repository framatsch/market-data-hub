# is_market_open Fix - Summary

## Problem

Die API gab `is_market_open: null` zurück für IWM und andere Symbole.

## Root Cause Analysis

### 1. Falscher ContractDetails-Zugriff
```python
# ❌ FALSCH (ib_insync style)
trading_hours = details[0].contractDetails.tradingHours

# ✅ RICHTIG (ib_async style)
trading_hours = details[0].tradingHours
```

### 2. Falsches Trading Hours Format
**Alt (erwartet):**
```
NYSESTD;0930-1600
```

**Neu (von IBKR geliefert):**
```
20260122:0400-20260122:2000;20260123:0400-20260123:2000;20260124:CLOSED;...
```

### 3. Fehlende/Falsche Zeitzonenbehandlung
**Problem 1 - Keine Zeitzone:**
```python
now = datetime.now()  # ❌ Lokale Serverzeit (CET/CEST)
```

**Problem 2 - Hardcoded Zeitzone:**
```python
now = datetime.now(ZoneInfo("America/New_York"))  # ❌ Nur für US-Börsen!
```

**IBKR liefert verschiedene Zeitzonen:**
- 🇺🇸 US Stocks: `US/Eastern`
- 🇩🇪 Deutsche Aktien: `MET`
- 🇯🇵 Japanische Aktien: `Japan`

## Solution

### 1. ContractDetails Fix
```python
cd = details[0]  # ib_async gibt ContractDetails direkt zurück
trading_hours = cd.tradingHours
timezone_id = cd.timeZoneId  # ← NEU: Zeitzone auch holen!
```

### 2. Neues Format Parser
```python
# Parse: "20260122:0930-20260122:1600"
day_entries = trading_hours.split(";")
for entry in day_entries:
    if entry.startswith(current_date_str):
        if "CLOSED" in entry:
            return False
        # Extract times: "20260122:0930-20260122:1600"
        time_parts = entry.split("-")
        start_time = time_parts[0].split(":")[1]  # "0930"
        end_time = time_parts[1].split(":")[1]    # "1600"
        return start_time <= current_time < end_time
```

### 3. Dynamische Zeitzone
```python
# Zeitzone von IBKR verwenden
timezone_map = {
    "US/Eastern": "America/New_York",
    "MET": "Europe/Berlin",
    "Japan": "Asia/Tokyo",
}
tz_name = timezone_map.get(timezone_id, timezone_id)
now = datetime.now(ZoneInfo(tz_name))
```

## Changes

### Modified Files
- `app/providers/ibkr.py`:
  - `_get_trading_hours()`: Gibt jetzt `(trading_hours, timezone_id)` tuple zurück
  - `_is_market_open()`: Nimmt `timezone_id` parameter und verwendet dynamische Zeitzone
  - `_get_market_open_status()`: Extrahiert beide Werte und gibt sie weiter

### Test Results

#### Before Fix
```json
{
  "is_market_open": null  ❌
}
```

#### After Fix
```json
{
  "is_market_open": true  ✅
}
```

## Benefits

✅ **Korrektes Format-Parsing**: Versteht neues IBKR-Format
✅ **Timezone-Aware**: Funktioniert für alle Börsen weltweit
✅ **Server-Location-Unabhängig**: Egal ob Server in US/Europa/Asien
✅ **Keine Hardcodes**: Nutzt IBKR-Daten direkt
✅ **Fallback**: US/Eastern als Default wenn keine Zeitzone geliefert wird

## Testing

### Test Scripts Created
1. `test_market_open_local.py` - Grundlegende Verbindung und Trading Hours
2. `test_trading_hours_parser.py` - Format-Parsing-Tests
3. `test_timezone_per_symbol.py` - Zeitzone pro Symbol/Börse
4. `demo_timezone_issue.py` - Demonstriert Zeitzonenproblem
5. `verify_market_open_fix.py` - End-to-End Verifikation

### Example Results
```
[IWM] US ETF
  - timeZoneId: 'US/Eastern'
  - is_market_open: True ✓

[BMW] German Stock
  - timeZoneId: 'MET'
  - is_market_open: False (außerhalb 09:00-17:45 MET)

[7203] Japanese Stock (Toyota)
  - timeZoneId: 'Japan'
  - is_market_open: False (außerhalb Japan Handelszeiten)
```

## API Impact

Users will now receive:
- **US stocks during trading hours (9:30-16:00 EST)**: `is_market_open: true`
- **US stocks outside trading hours**: `is_market_open: false`
- **European stocks during their hours**: `is_market_open: true/false` (korrekte Zeitzone)
- **No more null values** (unless truly unable to determine)
