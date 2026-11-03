"""Query and path parameter types shared by the routers.

Integers are bounded so an oversized value is a ``422 validation_error``: SQLite cannot bind
integers of 2**63 or more, and such a value would otherwise fail inside the query as a 500.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query

from app.schemas import MAX_STORED_INT

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=MAX_STORED_INT)]
VersionNumber = Annotated[int, Path(ge=1, le=MAX_STORED_INT)]
VersionQuery = Annotated[int, Query(ge=1, le=MAX_STORED_INT)]
