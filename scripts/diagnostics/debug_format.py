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
