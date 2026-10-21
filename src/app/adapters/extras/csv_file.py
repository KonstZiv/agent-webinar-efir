"""The export as a CSV file: a header row, commas, lines ending as RFC 4180 says (CRLF).

The cells come ready from ``app.core.extras.export``; this module only writes them. The text is
encoded as UTF-8 without BOM by the response.
"""

import csv
import io
from collections.abc import Iterable

from app.core.extras.export import COLUMNS, cells
from app.core.extras.ports import ExportRow


def to_csv(rows: Iterable[ExportRow]) -> str:
    """The header and one line per row; values with commas, quotes or line breaks are quoted.

    >>> to_csv([]) == ",".join(COLUMNS) + "\\r\\n"
    True
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows(cells(row) for row in rows)
    return buffer.getvalue()
