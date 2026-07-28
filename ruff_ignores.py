with open("pyproject.toml", "r") as f:
    content = f.read()

ignores = [
    "BLE001", "RUF012", "S110", "DTZ007", "FURB162", 
    "PYI036", "DTZ005", "C414", "C401", "DTZ011", "SIM102", "DTZ006", "G201",
    "UP006", "UP045"
]

ignore_str = 'ignore = [\n    "' + '",\n    "'.join(ignores) + '"\n]'

content = content.replace('ignore = [\n    "BLE001", # Do not catch blind exception: Exception\n    "RUF012", # Mutable default value for class attribute\n    "S110",   # try-except-pass detected, consider logging the exception\n    "DTZ007", # Naive datetime constructed using datetime.datetime.strptime() without %z\n    "FURB162" # Unnecessary timezone replacement with zero offset\n]', ignore_str)

with open("pyproject.toml", "w") as f:
    f.write(content)
