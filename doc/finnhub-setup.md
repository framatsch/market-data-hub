# 📰 Finnhub News Provider - Setup & Implementation Guide

## Overview

Die **FinnhubProvider** ist jetzt vollständig implementiert mit:
- ✅ Company News Endpoint (Company-spezifische News)
- ✅ Token Bucket Rate Limiting (60 Calls/Min)
- ✅ Sentiment Analysis (positive, negative, neutral)
- ✅ Automatic Category Detection (earnings, merger, product, legal)
- ✅ HTTP 429 Error Handling
- ✅ Async/Await Support

---

## 🔧 Setup

### 1. Finnhub API Key erhalten

1. Registrieren Sie sich kostenlos: https://finnhub.io
2. Kopieren Sie Ihren API Key
3. Fügen Sie ihn in `.env` ein:

```bash
FINNHUB_API_KEY=your_api_key_here
```

### 2. Konfiguration überprüfen

In `.env` sind folgende Einstellungen automatisch gesetzt:

```
# Finnhub Provider
FINNHUB_API_KEY=your_key_here
FINNHUB_BASE_URL=https://finnhub.io/api/v1
FINNHUB_RATE_LIMIT_PER_MIN=60
FINNHUB_FALLBACK_ON_RATE_LIMIT=True
```

---

## 🚀 Verwendung

### Quick Start

```bash
# API starten
uvicorn app.main:app --reload

# News abrufen (mit Finnhub Provider)
curl "http://localhost:8000/companies/AAPL/news?provider=finnhub"

# Mit Kategoriefilter
curl "http://localhost:8000/companies/AAPL/news?provider=finnhub&category=earnings"

# Als CSV
curl "http://localhost:8000/companies/AAPL/news?provider=finnhub&format=csv"
```

### API Endpoint

```
GET /companies/{symbol}/news
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | string | finnhub | Provider: "finnhub", "lseg", "ibkr", "mock" |
| `days` | integer | 30 | Last N days of news |
| `from_date` | string | - | Start date (YYYY-MM-DD) |
| `to_date` | string | today | End date (YYYY-MM-DD) |
| `category` | string | - | Filter: earnings, product, merger, legal |
| `limit` | integer | 20 | Articles per page (1-100) |
| `offset` | integer | 0 | Pagination offset |
| `format` | string | json | Response format: json, csv |
| `language` | string | en | Language (default: en) |

---

## 📊 Beispiele

### 1. Alle AAPL News (letzte 30 Tage)

```bash
curl "http://localhost:8000/companies/AAPL/news?provider=finnhub" | jq .
```

**Response:**

```json
{
  "data": [
    {
      "article_id": "finnhub:12345",
      "title": "Apple Reports Record Q4 Earnings",
      "summary": "Apple Inc. announced record-breaking quarterly earnings...",
      "published_at": "2026-01-03T15:30:00Z",
      "source": "Reuters",
      "url": "https://...",
      "full_text": null,
      "category": "earnings",
      "image": "https://...",
      "sentiment": {
        "positive": 0.85,
        "negative": 0.05,
        "neutral": 0.10
      }
    }
  ],
  "meta": {
    "total": 45,
    "limit": 20,
    "offset": 0,
    "has_more": true,
    "provider": "finnhub",
    "from_date": "2025-12-04",
    "to_date": "2026-01-04"
  }
}
```

### 2. Nur Earnings-Nachrichten

```bash
curl "http://localhost:8000/companies/TSLA/news?provider=finnhub&category=earnings"
```

### 3. Letzte 7 Tage mit Limit

```bash
curl "http://localhost:8000/companies/MSFT/news?provider=finnhub&days=7&limit=5"
```

---

## 🔄 Rate Limiting

**Finnhub Free Tier:** 60 Requests/Minute

### Wie funktioniert Token Bucket?

```
├─ Kapazität: 60 Tokens
├─ Regeneration: 1 Token pro Sekunde
├─ Bei Rate Limit: Automatischer Fallback zu Mock Provider
└─ Nachricht: "Finnhub rate limit exceeded (60/min)"
```

---

## 📁 Implementierungsdetails

### Dateien

```
app/providers/finnhub.py          ← Neue Provider Klasse
app/models/news.py                ← Erweitert um sentiment/image fields
app/config.py                     ← FINNHUB_* Einstellungen
app/providers/registry.py         ← FinnhubProvider registriert
app/api/routes_meta.py            ← Finnhub in /providers endpoint
app/dependencies.py               ← Finnhub als Default News Provider
scripts/diagnostics/test_finnhub_news.py  ← Test Script
```

---

## 🧪 Testing

```bash
python scripts/diagnostics/test_finnhub_news.py
```

---

## 🔗 Integration

- Registry: `self._providers["finnhub"] = FinnhubProvider()`
- Default News Provider: `dependencies.get_news_provider()`
- Metadata Endpoint: `/providers` listet finnhub als verfügbar

---

## ⚠️ Limitationen

- Rate Limit 60/min (Free Tier)
- Kein Full Text in API (nur Summary)
- Kategorisierung keyword-basiert (tuneable)
