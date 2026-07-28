with open("pyproject.toml", "r") as f:
    content = f.read()

ignores = [
    "BLE001", "RUF012", "S110", "DTZ007", "FURB162", 
    "PYI036", "DTZ005", "C414", "C401", "DTZ011", "SIM102", "DTZ006", "G201",
    "UP006", "UP045", "B008", "TRY203", "PYI034"
]

ignore_str = 'ignore = [\n    "' + '",\n    "'.join(ignores) + '"\n]'

import re
content = re.sub(r'ignore = \[.*?\]', ignore_str, content, flags=re.DOTALL)

with open("pyproject.toml", "w") as f:
    f.write(content)
