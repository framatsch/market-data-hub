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
mdmerge.py — Merge markdown files from directories and/or individual files into one.

Usage:
    python mdmerge.py -d ./openspec ./docs -o merged.md
    python mdmerge.py -d ./openspec -f extra.md notes.md -o merged.md
    python mdmerge.py -f file1.md file2.md -o merged.md

Options:
    -d  One or more directories to scan recursively for .md files
    -f  One or more individual .md files to include (appended after directories)
    -o  Output file (default: merged.md)
"""

import argparse
from pathlib import Path


def collect_from_dirs(dirs: list[str]) -> list[Path]:
    files = []
    for d in dirs:
        path = Path(d)
        if not path.is_dir():
            print(f"  ⚠️  Not a directory, skipping: {d}")
            continue
        found = sorted(path.rglob("*.md"))
        print(f"  📂 {d}: {len(found)} .md files")
        files.extend(found)
    return files


def collect_from_files(file_args: list[str]) -> list[Path]:
    files = []
    for f in file_args:
        path = Path(f)
        if not path.is_file():
            print(f"  ⚠️  File not found, skipping: {f}")
            continue
        if path.suffix.lower() != ".md":
            print(f"  ⚠️  Not a .md file, skipping: {f}")
            continue
        files.append(path)
    return files


def merge(files: list[Path], output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    print()
    with open(output, "w", encoding="utf-8") as out:
        for i, f in enumerate(files, 1):
            print(f"  [{i}/{len(files)}] {f}")
            out.write(f"#########################\n# {f}\n#########################\n\n")
            out.write(f.read_text(encoding="utf-8").strip())
            out.write("\n\n---\n\n")

    size_kb = output.stat().st_size / 1024
    print(f"\n  ✅ {output} ({len(files)} files, {size_kb:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Merge markdown files into one")
    parser.add_argument("-d", nargs="+", metavar="DIR",  default=[],  help="Directories to scan recursively")
    parser.add_argument("-f", nargs="+", metavar="FILE", default=[],  help="Individual .md files to include")
    parser.add_argument("-o", metavar="OUTPUT", default="merged.md",  help="Output file (default: merged.md)")
    args = parser.parse_args()

    if not args.d and not args.f:
        parser.print_help()
        return

    print()
    files = collect_from_dirs(args.d) + collect_from_files(args.f)

    if not files:
        print("  ❌ No .md files found.")
        return

    merge(files, Path(args.o))


if __name__ == "__main__":
    main()
