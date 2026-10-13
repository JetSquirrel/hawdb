# Copyright 2026 Nowledge
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTML table rendering for `QueryResult` in notebooks (no IPython needed)."""

from html import escape


def _cell(value):
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return repr(value)
    return str(value)


# Rows a notebook table renders before noting how many were omitted.
DISPLAY_ROW_LIMIT = 100


def render_html(columns, rows, total=None, limit=DISPLAY_ROW_LIMIT):
    """Render `rows` (dicts keyed by column) as an escaped HTML table.

    `rows` may already be cut down to the first `limit` rows, with `total`
    giving the full count; it defaults to `len(rows)`. At most `limit` rows are
    drawn; when more exist a note says how many were omitted.
    """
    if total is None:
        total = len(rows)
    if total == 0 and not columns:
        return "<p>(no rows)</p>"
    rows = rows[:limit]
    parts = ["<table>", "<thead><tr>"]
    parts.extend(f"<th>{escape(str(column))}</th>" for column in columns)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend(
            f"<td>{escape(_cell(row.get(column)))}</td>" for column in columns
        )
        parts.append("</tr>")
    parts.append("</tbody></table>")
    if total == 0:
        parts.append("<p>(no rows)</p>")
    omitted = total - len(rows)
    if omitted > 0:
        parts.append(
            f"<p>{omitted} more row{'s' if omitted != 1 else ''} not shown "
            f"({total} total).</p>"
        )
    return "".join(parts)
