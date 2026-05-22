import asyncio

from app.providers.schwab import SchwabProvider


async def main() -> None:
    provider = SchwabProvider()
    quote = await provider.get_last_price("AAPL")
    print("Schwab connection successful")
    print(quote.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
