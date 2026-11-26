"""SQL quoting helpers. Pure Python (no QGIS), so CI can test them.

Table and schema names are validated against a strict pattern before they go anywhere near
SQL; values are escaped as literals. Nothing user-supplied is ever pasted in raw.
"""
import math
import re
from string import Template

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


# ---- the few queries the loader runs ----
# Each query is a fixed template. Only identifiers that passed quote_ident, values that went
# through quote_literal, and integers are substituted into it, in a single pass (a "$" inside
# a value is never expanded again). Keeping them here keeps every SQL string in one place.

def qualified(schema, table) -> str:
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def _fill(template: str, **parts) -> str:
    return Template(template).substitute(**parts)


def count_rows_sql(schema, table) -> str:
    return _fill("SELECT count(*) FROM $table", table=qualified(schema, table))


def distinct_srid_sql(schema, table, geometry_column="geom") -> str:
    return _fill("SELECT DISTINCT ST_SRID($geom) FROM $table WHERE $geom IS NOT NULL",
                 geom=quote_ident(geometry_column), table=qualified(schema, table))


def run_log_insert_sql(schema, log_table, run_id, source, table, read, loaded, quarantined,
                       status) -> str:
    return _fill(
        "INSERT INTO $log (run_id, source, table_name, features_read, features_loaded, "
        "features_quarantined, status) VALUES ($v_run, $v_source, $v_table, $v_read, "
        "$v_loaded, $v_quarantined, $v_status);",
        log=qualified(schema, log_table), v_run=quote_literal(run_id),
        v_source=quote_literal(source), v_table=quote_literal(table),
        v_read=int(read), v_loaded=int(loaded), v_quarantined=int(quarantined),
        v_status=quote_literal(status))
