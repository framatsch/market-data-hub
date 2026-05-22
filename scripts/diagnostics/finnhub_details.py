# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import trafilatura

# Die URL aus deinem Finnhub-JSON
url = "https://finnhub.io/api/news?id=b9019f1fefd583056c17ca57a24982780ebc4ccd791ee9479bfa9ae930673452"

# 1. Die Seite herunterladen (folgt automatisch Redirects)
downloaded = trafilatura.fetch_url(url)

# 2. Den Inhalt extrahieren und direkt als Markdown formatieren
# include_tables=True ist nützlich für Finanzdaten
markdown_content = trafilatura.extract(downloaded, output_format="markdown", include_tables=True)

print(markdown_content)