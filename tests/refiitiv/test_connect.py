import refinitiv.data as rd
from refinitiv.data.content import historical_pricing, search
from dotenv import load_dotenv
import os


def convert_to_ric(ticker):
    try:
        response = search.Definition(
            view=search.Views.EQUITY_QUOTES,
            query=ticker,
            # Search exactly for the ticker symbol
            filter=f"TickerSymbol eq '{ticker}'",
            select="RIC, DisplayName, TickerSymbol, ExchCode",
            top=1
        ).get_data()

        if not response.data.df.empty:
            return response.data.df.iloc[0]['RIC']
        else:
            return "No RIC found"
    except Exception as e:
        return f"Error: {e}"


try:
    load_dotenv()
    session = rd.session.platform.Definition(
        app_key=os.getenv("LSEG_APP_KEY"),
        grant=rd.session.platform.GrantPassword(
            username=os.getenv("LSEG_USERNAME"),
            password=os.getenv("LSEG_PASSWORD")
        ),
        signon_control=True
    ).get_session()

    session.open()
    rd.session.set_default(session)
    print("Status: Connection to LSEG platform successful!")

    instrument = convert_to_ric("AAPL")  # Example ticker for Apple Inc.
    print(f"Resolved instrument: {instrument}")

    print(f"\nFetching historical data for {instrument}...")

    response = historical_pricing.summaries.Definition(
        universe=instrument,
        interval=historical_pricing.Intervals.DAILY,
        count=1  # Fetches the most recent available day
    ).get_data()

    if response.data.df is not None and not response.data.df.empty:
        df = response.data.df
        # Display the relevant columns
        # Typical columns are 'TRDPRC_1' (price) or 'CLOSE'
        print("\nLast available trading day:")
        print(df)
        #print(df[['Date', 'CLOSE']])
    else:
        print("No data found for this instrument.")

    session.close()

except Exception as e:
    print(f"Error: {e}")
