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

#!/usr/bin/env python3
"""
Debug parsing of new IBKR trading hours format
"""

new_format = "20260122:0400-20260122:2000;20260123:0400-20260123:2000;20260124:CLOSED;20260125:CLOSED;20260126:0400-20260126:2000;20260127:0400-20260127:2000"

print("Raw format:")
print(f"  {new_format}\n")

print("Split by semicolon:")
day_entries = new_format.split(";")
for i, entry in enumerate(day_entries):
    print(f"  [{i}] {entry}")

print("\nLooking at first entry:")
entry = day_entries[0]
print(f"  Entry: {entry}")
print(f"  Split by colon:")
parts = entry.split(":")
for i, part in enumerate(parts):
    print(f"    [{i}] {part}")

print("\nThe problem:")
print("  Entry '20260122:0400-20260122:2000' splits into:")
print("    [0] '20260122'")
print("    [1] '0400-20260122'")
print("    [2] '2000'")
print(f"  So parts[1] = '{parts[1]}' (contains date inside!)")
print(f"  And parts[3] doesn't exist!")

print("\nCorrect parsing:")
print("  Need to extract times from the DASH part, not split by colon")
if "-" in entry:
    dash_part = entry.split("-")
    print(f"  Split by dash: {dash_part}")
    start = dash_part[0]  # "20260122:0400"
    end = dash_part[1]     # "20260122:2000"
    print(f"  Start: {start} → extract time: {start.split(':')[1]}")
    print(f"  End: {end} → extract time: {end.split(':')[1]}")
