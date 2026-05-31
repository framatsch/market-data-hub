from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

import httpx

from app.config import settings
from app.models.price import PriceBar, PriceQuote
from app.providers.base import BasePriceProvider
from app.utils.errors import AppError, ProviderError, map_httpx_http_error
from app.utils.secrets import unwrap_secret


class PrixeProvider(BasePriceProvider):
    """Prixe provider for latest stock prices via POST /api/last_sold."""

    def __init__(self) -> None:
        self._api_key = unwrap_secret(settings.PRIXE_API_KEY)
        if not self._api_key:
            raise ProviderError(
                "Prixe API key is not configured.",
                code="PROVIDER_NOT_AVAILABLE",
                details={"provider": "prixe", "setting": "PRIXE_API_KEY"},
            )

        self._base_url = settings.PRIXE_BASE_URL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=settings.PROVIDER_REQUEST_TIMEOUT,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_last_price(
        self,
        symbol: str,
        market_data_type: Optional[int] = None,
        sec_type: str = "stock",
    ) -> PriceQuote:
        del market_data_type
        del sec_type

        normalized_symbol = symbol.upper()
        client = await self._get_client()

        try:
            response = await client.post("/api/last_sold", json={"symbol": normalized_symbol})
            response.raise_for_status()
            payload = response.json()
            return self._map_last_sold_payload(normalized_symbol, payload)
        except httpx.HTTPStatusError as exc:
            raise map_httpx_http_error(
                provider="prixe",
                error=exc,
                entity="Ticker",
                identifier=normalized_symbol,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Prixe request timed out.",
                code="PROVIDER_TIMEOUT",
                details={"provider": "prixe", "symbol": normalized_symbol},
            ) from exc
        except AppError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Unexpected Prixe provider error: {exc}",
                details={"provider": "prixe", "symbol": normalized_symbol},
            ) from exc

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        sec_type: str = "stock",
    ) -> List[PriceBar]:
        del sec_type

        normalized_symbol = symbol.upper()
        normalized_interval = interval.lower()
        supported_intervals = {
            "1m",
            "2m",
            "5m",
            "15m",
            "30m",
            "60m",
            "90m",
            "1h",
            "1d",
            "5d",
            "1wk",
            "1mo",
            "3mo",
        }

        if normalized_interval not in supported_intervals:
            raise ProviderError(
                f"Unsupported Prixe interval '{interval}'.",
                details={
                    "provider": "prixe",
                    "interval": interval,
                    "supported_intervals": sorted(supported_intervals),
                },
            )

        client = await self._get_client()

        request_payload = {
            "ticker": normalized_symbol,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "interval": normalized_interval,
        }

        try:
            response = await client.post("/api/price", json=request_payload)
            response.raise_for_status()
            payload = response.json()
            return self._map_historical_payload(
                symbol=normalized_symbol,
                payload=payload,
                start=start,
                end=end,
            )
        except httpx.HTTPStatusError as exc:
            raise map_httpx_http_error(
                provider="prixe",
                error=exc,
                entity="Ticker",
                identifier=normalized_symbol,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Prixe historical request timed out.",
                code="PROVIDER_TIMEOUT",
                details={"provider": "prixe", "symbol": normalized_symbol},
            ) from exc
        except AppError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Unexpected Prixe historical error: {exc}",
                details={"provider": "prixe", "symbol": normalized_symbol},
            ) from exc

    def _map_last_sold_payload(self, symbol: str, payload: object) -> PriceQuote:
        if not isinstance(payload, dict):
            raise ProviderError(
                "Invalid response payload from Prixe.",
                details={"provider": "prixe", "payload_type": type(payload).__name__},
            )

        result = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        if not isinstance(result, dict):
            raise ProviderError(
                "Invalid result object from Prixe.",
                details={"provider": "prixe"},
            )

        symbol_value = str(result.get("symbol") or symbol).upper()
        price_value = result.get("last_sold")
        if price_value is None:
            price_value = result.get("price")

        if price_value is None:
            raise ProviderError(
                "Prixe response missing price field.",
                details={"provider": "prixe", "symbol": symbol_value},
            )

        bid_value = result.get("bid")
        ask_value = result.get("ask")

        timestamp = self._parse_timestamp(result.get("timestamp") or result.get("updated_at"))

        return PriceQuote(
            symbol=symbol_value,
            price=Decimal(str(price_value)),
            currency=str(result.get("currency") or "USD").upper(),
            timestamp=timestamp,
            provider="prixe",
            bid=Decimal(str(bid_value)) if bid_value is not None else None,
            ask=Decimal(str(ask_value)) if ask_value is not None else None,
        )

    def _map_historical_payload(
        self,
        *,
        symbol: str,
        payload: object,
        start: datetime,
        end: datetime,
    ) -> List[PriceBar]:
        if not isinstance(payload, dict):
            raise ProviderError(
                "Invalid historical payload from Prixe.",
                details={"provider": "prixe", "payload_type": type(payload).__name__},
            )

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(
                "Missing or invalid 'data' in Prixe historical payload.",
                details={"provider": "prixe", "symbol": symbol},
            )

        timestamps = data.get("timestamp")
        opens = data.get("open")
        highs = data.get("high")
        lows = data.get("low")
        closes = data.get("close")
        volumes = data.get("volume")

        arrays = {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        }
        if not all(isinstance(v, list) for v in arrays.values()):
            raise ProviderError(
                "Prixe historical response is missing OHLC/timestamp arrays.",
                details={"provider": "prixe", "symbol": symbol},
            )

        lengths = {name: len(values) for name, values in arrays.items()}
        if len(set(lengths.values())) != 1:
            raise ProviderError(
                "Prixe historical arrays have mismatched lengths.",
                details={"provider": "prixe", "symbol": symbol, "lengths": lengths},
            )

        if volumes is not None and isinstance(volumes, list) and len(volumes) != lengths["timestamp"]:
            raise ProviderError(
                "Prixe historical volume array length mismatch.",
                details={"provider": "prixe", "symbol": symbol},
            )

        bars: List[PriceBar] = []
        for idx, ts in enumerate(timestamps):
            bar_start = self._parse_timestamp(ts)
            if bar_start.tzinfo is None:
                bar_start = bar_start.replace(tzinfo=timezone.utc)

            volume_value = 0
            if isinstance(volumes, list):
                volume_value = int(volumes[idx] or 0)

            bars.append(
                PriceBar(
                    symbol=str(data.get("ticker") or symbol).upper(),
                    start=bar_start,
                    end=bar_start,
                    open=Decimal(str(opens[idx])),
                    high=Decimal(str(highs[idx])),
                    low=Decimal(str(lows[idx])),
                    close=Decimal(str(closes[idx])),
                    volume=volume_value,
                    provider="prixe",
                )
            )

        start_utc = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        end_utc = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        return [bar for bar in bars if start_utc <= bar.start <= end_utc]

    def _parse_timestamp(self, value: object) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)
