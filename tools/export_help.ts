#!/usr/bin/env node
/*
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
/**
 * export_help.ts — Export the Trade Sensei help glossary to a Markdown file.
 *
 * Usage:
 *   npm run export-help                          # writes docs/HELP_GLOSSARY.md
 *   npm run export-help -- --output my/path.md  # custom output path
 *
 * Requires tsx (installed as devDependency or globally):
 *   npx tsx tools/export_help.ts
 */

import * as fs from "fs";
import * as path from "path";
import { HELP_SECTIONS } from "../frontend/lib/help-content";

// ─── CLI args ──────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const outputIdx = args.indexOf("--output");
const outputArg = outputIdx !== -1 ? args[outputIdx + 1] : undefined;
const outputPath = outputArg
  ? path.resolve(outputArg)
  : path.resolve(__dirname, "../docs/HELP_GLOSSARY.md");

// ─── Render ────────────────────────────────────────────────────────────────────

function render(): string {
  const lines: string[] = [
    "# Trade Sensei — Help & Reference Glossary",
    "",
    "> Auto-generated from `frontend/lib/help-content.ts`. Do not edit manually.",
    "> Re-generate with: `npm run export-help` (from the `frontend/` directory)",
    "",
    "---",
    "",
    "## Table of Contents",
    "",
  ];

  // TOC
  for (const section of HELP_SECTIONS) {
    const anchor = section.heading.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    lines.push(`- [${section.heading}](#${anchor})`);
    for (const entry of section.entries) {
      const entryAnchor = entry.id;
      lines.push(`  - [${entry.label}](#${entryAnchor})`);
    }
  }
  lines.push("");

  // Content
  for (const section of HELP_SECTIONS) {
    lines.push(`---`, "", `## ${section.heading}`, "");

    for (const entry of section.entries) {
      lines.push(`### ${entry.label} {#${entry.id}}`, "");
      lines.push(`**${entry.summary}**`, "");
      lines.push(entry.detail, "");

      if (entry.formula) {
        lines.push("**Formula:**", "", `\`\`\``, entry.formula, `\`\`\``, "");
      }
      if (entry.good) {
        lines.push(`> ✅ **Good:** ${entry.good}`, "");
      }
      if (entry.bad) {
        lines.push(`> ⚠️ **Watch out:** ${entry.bad}`, "");
      }
    }
  }

  lines.push("---", "", `*Generated: ${new Date().toISOString()}*`, "");
  return lines.join("\n");
}

// ─── Write ─────────────────────────────────────────────────────────────────────

const markdown = render();
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, markdown, "utf8");

console.log(`✓ Help glossary written to: ${outputPath}`);
console.log(`  Sections: ${HELP_SECTIONS.length}`);
console.log(`  Entries:  ${HELP_SECTIONS.reduce((n, s) => n + s.entries.length, 0)}`);
