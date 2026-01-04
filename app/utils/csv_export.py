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

    if not data:
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
