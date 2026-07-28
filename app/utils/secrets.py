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

"""Utility for safely unwrapping pydantic SecretStr values.

Usage:
    from app.utils.secrets import unwrap_secret
    api_key = unwrap_secret(settings.FINNHUB_API_KEY)
"""


def unwrap_secret(value: object) -> str | None:
    """Return the plain string value of a SecretStr or a regular str.

    Works transparently with both pydantic.SecretStr and plain str so that
    call sites don't need to branch on the type.
    """
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return str(value.get_secret_value())
    return str(value)
