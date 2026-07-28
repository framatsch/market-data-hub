import re
with open("pyproject.toml", "r") as f:
    content = f.read()

content = content.replace('"PYI034"', '"PYI034",\n    "LOG014"')

with open("pyproject.toml", "w") as f:
    f.write(content)
