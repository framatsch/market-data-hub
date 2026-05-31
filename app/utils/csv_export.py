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

"""CSV export utilities for price data."""

import csv
import io
from typing import Any
from decimal import Decimal


def to_csv(data: Any, filename: str = "export.csv") -> tuple[str, bytes]:
    """
    Convert data to CSV format.

    Args:
        data: Single object, list of objects, or dict to convert
        filename: Suggested filename for download

    Returns:
        Tuple of (content_type, csv_bytes)
    """
    output = io.StringIO()

    # Handle single object (convert to list)
    if not isinstance(data, list):
        data = [data]

    if not data or data[0] is None:
        # Return empty CSV with header if data is empty
        output.write("")
        return ("text/csv", output.getvalue().encode())

    # Get first item to determine structure
    first_item = data[0]

    if isinstance(first_item, dict):
        # Dictionary data
        fieldnames = first_item.keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            # Convert Decimal to string for CSV
            row_converted = {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            writer.writerow(row_converted)
    else:
        # Pydantic model - convert to dict
        fieldnames = first_item.model_fields.keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in data:
            row_dict = item.model_dump()
            # Convert Decimal to string for CSV
            row_converted = {k: str(v) if isinstance(v, Decimal) else v for k, v in row_dict.items()}
            writer.writerow(row_converted)

    csv_bytes = output.getvalue().encode()
    return ("text/csv", csv_bytes)
