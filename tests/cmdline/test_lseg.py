import refinitiv.data as rd
from refinitiv.data.content import historical_pricing, search
import datetime
from dotenv import load_dotenv
import os





def convert_to_ric(ticker):
    try:
        response = search.Definition(
            view=search.Views.EQUITY_QUOTES,
            query=ticker,
            # Wir suchen exakt nach dem Ticker-Symbol
            filter=f"TickerSymbol eq '{ticker}'",
            select="RIC, DisplayName, TickerSymbol, ExchCode",
            top=1
        ).get_data()

        if not response.data.df.empty:
            return response.data.df.iloc[0]['RIC']
        else:
            return "Kein RIC gefunden"
    except Exception as e:
        return f"Fehler: {e}"


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
    print("Status: Verbindung zur LSEG Plattform erfolgreich!")


    instrument = convert_to_ric("AAPL")  # Beispiel ISIN für Rigel Pharmaceuticals plc
    print(f"Aufgelöstes Instrument: {instrument}")

    print(f"\nFrage historische Daten für {instrument} ab...")

    response = historical_pricing.summaries.Definition(
        universe=instrument,
        interval=historical_pricing.Intervals.DAILY,
        count=1 # Holt den aktuellsten verfügbaren Tag
    ).get_data()

    if response.data.df is not None and not response.data.df.empty:
        df = response.data.df
        # Wir lassen uns die relevanten Spalten anzeigen
        # Typische Spalten sind 'TRDPRC_1' (Preis) oder 'CLOSE'
        print("\nLetzter verfügbarer Handelstag:")
        print(df)
        #print(df[['Date', 'CLOSE']])
    else:
        print("Keine Daten für dieses Instrument gefunden.")

    session.close()

except Exception as e:
    print(f"Fehler: {e}")

