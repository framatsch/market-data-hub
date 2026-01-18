# Market Open Status Feature

## Overview
Die `get_last_price()` Methode gibt nun zusätzlich zur Preisquote einen **`is_market_open`** Flag zurück, der anzeigt, ob der Markt aktuell geöffnet ist.

## Implementation Details

### Model Update
Die `PriceQuote` hat ein neues optionales Feld:

```python
class PriceQuote(BaseModel):
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime
    provider: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume: Optional[int] = None
    is_market_open: Optional[bool] = None  # ← NEW
```

### IBKR Provider Methods

#### `_get_trading_hours(contract: Contract) -> Optional[str]`
- Ruft die `tradingHours` vom Contract Details ab
- Format: `"NYSESTD;0930-1600"` oder `"NYSESTD;0930-1600:CLOSED;20220101-20220102"`
- Gibt `None` zurück wenn nicht verfügbar

#### `_is_market_open(trading_hours: Optional[str]) -> Optional[bool]`
- **Logik:**
  1. Parst den `tradingHours` String
  2. Prüft ob das aktuelle Datum in CLOSED Ranges liegt
  3. Prüft ob die aktuelle Zeit innerhalb der Trading Hours liegt

- **Rückgabewert:**
  - `True` = Markt ist offen
  - `False` = Markt ist geschlossen
  - `None` = Status unbekannt

#### `_get_market_open_status(contract: Contract) -> Optional[bool]`
- Wrapper-Methode die die obigen kombiniert
- Wird in `get_last_price()` aufgerufen

### Beispiel Response

```json
{
  "symbol": "AAPL",
  "price": 150.25,
  "currency": "USD",
  "timestamp": "2024-01-18T15:30:00",
  "provider": "ibkr",
  "bid": 150.20,
  "ask": 150.30,
  "volume": 1000000,
  "is_market_open": true
}
```

## Zeitzone Anmerkung
Die aktuelle Zeit wird über `datetime.now()` abgerufen. Für genaue Ergebnisse sollte der Server in der **US/Eastern** Zeitzone laufen oder die Logik angepasst werden um die korrekte Marktzone zu berücksichtigen.

## Fehlerbehandlung
- Falls Trading Hours nicht verfügbar sind: `is_market_open` = `None`
- Ungültige Formate werden geloggt und geben `None` zurück
- Kein Exception wird geworfen; API bleibt verfügbar

## Testing
```python
# Beispiel Test
quote = await ibkr_provider.get_last_price("AAPL")
print(f"Market open: {quote.is_market_open}")
```

## CI/CD
✅ Alle Änderungen passen den Code-Style-Anforderungen (ruff check) an
