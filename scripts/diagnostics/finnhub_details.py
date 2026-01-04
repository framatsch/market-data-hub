import trafilatura

# Die URL aus deinem Finnhub-JSON
url = "https://finnhub.io/api/news?id=b9019f1fefd583056c17ca57a24982780ebc4ccd791ee9479bfa9ae930673452"

# 1. Die Seite herunterladen (folgt automatisch Redirects)
downloaded = trafilatura.fetch_url(url)

# 2. Den Inhalt extrahieren und direkt als Markdown formatieren
# include_tables=True ist nützlich für Finanzdaten
markdown_content = trafilatura.extract(downloaded, output_format="markdown", include_tables=True)

print(markdown_content)