"""Shared annotations for tool parameters."""

from typing import Annotated

from pydantic import BeforeValidator

# An optional free-text parameter: declare it `OptionalText = ""`, and treat "" as
# not given. mcp's FuncMetadata.pre_parse_json runs json.loads on a string argument
# unless its field annotation is exactly `str`, so `str | None` turned text that
# parses as JSON (a drive#commentRegion anchor, "null", "[1, 2]") into another type
# before validation (PR #1563 round 2, #1569). Pydantic keeps the validator in the
# field's metadata, leaving the annotation exactly `str`, so the text is never
# pre-parsed, and an explicit null from a client still validates, as "" (round 3).
OptionalText = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]
