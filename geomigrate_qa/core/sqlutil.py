"""SQL quoting helpers. Pure Python (no QGIS), so CI can test them.

Table and schema names are validated against a strict pattern before they go anywhere near
SQL; values are escaped as literals. Nothing user-supplied is ever pasted in raw.
"""
import math
import re

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def quote_ident(name) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise ValueError(
            f"Invalid SQL identifier {name!r}: use letters, digits and underscores, "
            "starting with a letter or underscore (max 63 characters).")
    return f'"{name}"'


def quote_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cannot store NaN or infinity as a SQL number.")
        return repr(value)
    text = str(value)
    if "\x00" in text:
        raise ValueError("Text containing NUL characters cannot be stored.")
    return "'" + text.replace("'", "''") + "'"
