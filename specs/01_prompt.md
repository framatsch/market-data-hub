You previously designed a FastAPI-based data service with pluggable providers (e.g., IBKR and LSEG/Refinitiv) and a clean provider-agnostic API.

Now extend the design and implementation to take explicit advantage of **LSEG / Refinitiv capabilities**, especially in the following domains:

- Deep historical pricing (Tick History + OHLC time series)
- Global company fundamentals and classification
- ESG data
- Financial news and sentiment (Reuters + 10,000+ sources)
- Macroeconomic time series (Datastream / Economic Indicators)
- Research/estimates where appropriate

The goal is to keep the existing architecture (providers + aggregator FastAPI service), but:

1. **Enrich the provider interfaces**  
   Extend the provider abstraction layer so that LSEG's strengths are first-class citizens:

   - In `providers/base.py`, add or refine the following abstract base classes:

     ```python
     class BasePriceProvider(ABC):
         async def get_last_price(self, symbol: str) -> PriceQuote: ...
         async def get_historical_prices(
             self,
             symbol: str,
             interval: str,   # e.g. '1m', '5m', '1h', '1d'
             start: datetime,
             end: datetime,
         ) -> list[PriceBar]: ...
         async def get_tick_history(
             self,
             symbol: str,
             start: datetime,
             end: datetime,
         ) -> list[TickRecord]: ...
     ```

     ```python
     class BaseCompanyProvider(ABC):
         async def get_company_profile(self, symbol: str) -> CompanyProfile: ...
         async def get_fundamentals(
             self,
             symbol: str,
             as_reported: bool = False,
         ) -> FundamentalsSnapshot: ...
         async def get_estimates(
             self,
             symbol: str,
         ) -> AnalystEstimates: ...
     ```

     ```python
     class BaseESGProvider(ABC):
         async def get_esg_scores(self, symbol: str) -> ESGScores: ...
         async def get_esg_measures(self, symbol: str) -> ESGMeasures: ...
     ```

     ```python
     class BaseNewsProvider(ABC):
         async def get_latest_news(
             self,
             symbol: str,
             limit: int = 20,
         ) -> list[NewsItem]: ...

         async def get_news_with_sentiment(
             self,
             symbol: str,
             limit: int = 50,
         ) -> list[NewsWithSentiment]: ...
     ```

     ```python
     class BaseMacroProvider(ABC):
         async def get_macro_timeseries(
             self,
             series_code: str,   # e.g. "US.CPI", "DE.GDP", etc.
             start: date,
             end: date,
         ) -> MacroTimeSeries: ...
     ```

   - Make sure all new types (`TickRecord`, `FundamentalsSnapshot`, `AnalystEstimates`, `ESGScores`, `ESGMeasures`, `NewsItem`, `NewsWithSentiment`, `MacroTimeSeries`) are defined as Pydantic models in `app/models/`.

2. **Implement an LSEG provider that exposes these capabilities**

   In `providers/lseg.py`, provide a **stubbed but realistic implementation** that conforms to the new base interfaces:

   - `LSEGPriceProvider`:
     - `get_historical_prices` should simulate rich intraday and daily time series.
     - `get_tick_history` should simulate tick-level data (trade/quote records) as if coming from Tick History.

   - `LSEGCompanyProvider`:
     - `get_company_profile` returns basic company metadata.
     - `get_fundamentals` returns a structure that looks like income statement, balance sheet and cashflow sections.
     - `get_estimates` returns a few exemplar analyst estimates (EPS, revenue, etc.).

   - `LSEGESGProvider`:
     - `get_esg_scores` and `get_esg_measures` return dummy scores/metrics in a realistic structure.

   - `LSEGNewsProvider`:
     - `get_latest_news` returns a list of news headlines with timestamps and sources (e.g., "Reuters", "OtherSource").
     - `get_news_with_sentiment` additionally returns a sentiment score and simple tags.

   - `LSEGMacroProvider`:
     - `get_macro_timeseries` returns macro time series (date + value) for codes like `US.CPI`, `DE.GDP`, etc.

   The actual HTTP calls to LSEG / Refinitiv APIs should NOT be implemented. Instead:
   - clearly mark where calls to RDP, Tick History, Datastream, etc. would go,
   - keep all URLs and credentials in the configuration layer,
   - structure the code so that real implementations can later be plugged in by replacing the stub methods.

3. **Update the provider registry**

   In `providers/registry.py`:

   - Register LSEG as a multi-role provider, e.g.:

     ```python
     PROVIDERS = {
         "ibkr": {
             "price": ibkr_price_provider,
             "company": ibkr_company_provider,
             "options": ibkr_options_provider,
         },
         "lseg": {
             "price": lseg_price_provider,
             "company": lseg_company_provider,
             "esg": lseg_esg_provider,
             "news": lseg_news_provider,
             "macro": lseg_macro_provider,
         },
     }
     ```

   - Extend the getter functions to support the new roles:
     - `get_esg_provider(name: str | None) -> BaseESGProvider`
     - `get_news_provider(name: str | None) -> BaseNewsProvider`
     - `get_macro_provider(name: str | None) -> BaseMacroProvider`

   - Respect defaults from the config layer, e.g.:
     - `DEFAULT_ESG_PROVIDER = "lseg"`
     - `DEFAULT_NEWS_PROVIDER = "lseg"`
     - `DEFAULT_MACRO_PROVIDER = "lseg"`

4. **Extend the FastAPI routes**

   Under `app/api/`, add new routes:

   - `routes_fundamentals.py`:
     - `GET /fundamentals/{symbol}` → returns `FundamentalsSnapshot`
     - `GET /fundamentals/{symbol}/estimates` → returns `AnalystEstimates`

   - `routes_esg.py`:
     - `GET /esg/{symbol}/scores` → `ESGScores`
     - `GET /esg/{symbol}/measures` → `ESGMeasures`

   - `routes_news.py`:
     - `GET /news/{symbol}` → list of `NewsItem`
     - `GET /news/{symbol}/sentiment` → list of `NewsWithSentiment`

   - `routes_macro.py`:
     - `GET /macro/{series_code}` with `start`, `end` query params → `MacroTimeSeries`

   - In `routes_prices.py`, add:
     - `GET /prices/{symbol}/ticks` with `start`, `end`, `provider` → list of `TickRecord`

   Each endpoint should:
   - accept an optional `provider` query parameter to override the default,
   - call the appropriate provider via the registry,
   - return strongly typed Pydantic models,
   - have descriptive summaries and docstrings so that Swagger/OpenAPI is clear.

5. **Clarify IBKR vs LSEG roles in code and docs**

   In the `README.md`:

   - Add a short matrix explaining which data domains are primarily backed by IBKR vs LSEG in this service, e.g.:

     - IBKR: best for **trading-related live data** and **account/portfolio**.
     - LSEG: best for **deep historical data**, **fundamentals**, **ESG**, **news**, **macro**.

   - Document configuration examples:
     - "Use IBKR as default price provider, but LSEG for fundamentals and news."
     - Show sample requests such as:
       - `GET /prices/QCOM/last?provider=ibkr`
       - `GET /fundamentals/QCOM?provider=lseg`
       - `GET /news/QCOM/sentiment?provider=lseg`
       - `GET /macro/US.CPI?start=2010-01-01&end=2025-01-01`

6. **Non-functional aspects**

   - Keep the code fully async and type-safe.
   - Reuse the existing error model for new providers (e.g., `DataNotFoundError`, `ProviderTimeoutError`).
   - Add TODO comments where real LSEG SDK/API integration should be added in the future.

---

**Deliverables for this extension:**

- Updated provider base classes and new ones (ESG, News, Macro).
- Extended LSEG provider implementations with stubbed logic.
- Updated provider registry to support new roles and defaults.
- New FastAPI route modules (`routes_fundamentals.py`, `routes_esg.py`, `routes_news.py`, `routes_macro.py`) plus added tick-history endpoint.
- Updated `README.md` explaining IBKR vs LSEG roles and providing example configurations and API calls.
