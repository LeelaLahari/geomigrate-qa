"""Load layers into PostGIS safely: stage, verify, then swap into place in one transaction.

1. Each layer is exported to a staging schema and checked (row count, SRID, spatial index).
2. A single multi-statement SQL string then moves every staged table into the target schema
   and writes the run log. PostgreSQL runs such a string as one transaction, so the target
   either gets the whole run or is left exactly as it was.
Uses QGIS's own PostgreSQL provider, so no extra Python packages are needed.
"""
import uuid
from dataclasses import dataclass, field

from qgis.core import (
    QgsDataSourceUri,
    QgsProviderConnectionException,
    QgsProviderRegistry,
    QgsVectorLayerExporter,
)

from .sqlutil import (
    count_rows_sql,
    distinct_srid_sql,
    quote_ident,
    quote_literal,
    run_log_insert_sql,
)

GEOMETRY_COLUMN = "geom"
RUN_LOG_TABLE = "geomigrate_run_log"


class LoadError(RuntimeError):
    """The load failed; the target schema was not changed."""


@dataclass(frozen=True)
class PgConnection:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "geomigrate"
    user: str = "postgres"
    password: str = ""

    def data_source(self, schema=None, table=None) -> QgsDataSourceUri:
        uri = QgsDataSourceUri()
        uri.setConnection(self.host, str(self.port), self.dbname, self.user, self.password)
        if table:
            uri.setDataSource(schema, table, GEOMETRY_COLUMN)
        return uri

    def connect(self):
        metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
        if metadata is None:
            raise LoadError("This QGIS has no PostgreSQL provider.")
        return metadata.createConnection(self.data_source().uri(False), {})


@dataclass
class LoadResult:
    run_id: str
    schema: str
    expected: dict = field(default_factory=dict)  # table -> features we meant to load
    loaded: dict = field(default_factory=dict)    # table -> rows now in PostGIS

    @property
    def ok(self):
        return self.expected == self.loaded


def _export_ok(code):
    return int(getattr(code, "value", code)) == 0


def _run(conn, sql):
    try:
        return conn.executeSql(sql)
    except QgsProviderConnectionException as exc:
        raise LoadError(str(exc)) from exc


def _swap_sql(schema, staging, tables, run_id, source, stats, overwrite):
    s, g = quote_ident(schema), quote_ident(staging)
    log = f"{s}.{quote_ident(RUN_LOG_TABLE)}"
    parts = [
        f"CREATE SCHEMA IF NOT EXISTS {s};",
        (f"CREATE TABLE IF NOT EXISTS {log} (run_id text, run_at timestamptz DEFAULT now(), "
         "source text, table_name text, features_read integer, features_loaded integer, "
         "features_quarantined integer, status text);"),
    ]
    for table, loaded in tables.items():
        t = quote_ident(table)
        if overwrite:
            parts.append(f"DROP TABLE IF EXISTS {s}.{t};")
        parts.append(f"ALTER TABLE {g}.{t} SET SCHEMA {s};")
        read = stats.get(table, {}).get("read", loaded)
        parts.append(run_log_insert_sql(
            schema, RUN_LOG_TABLE, run_id, source, table, read, loaded,
            max(read - loaded, 0), "loaded"))
    return " ".join(parts)


def _drop_staging(conn, staging, tables):
    try:
        for table in tables:
            conn.executeSql(f"DROP TABLE IF EXISTS {quote_ident(staging)}.{quote_ident(table)}")
        conn.executeSql(f"DROP SCHEMA IF EXISTS {quote_ident(staging)}")
    except QgsProviderConnectionException:
        pass  # leftovers in staging are harmless and are cleared on the next run


def count_rows(pg: PgConnection, schema, table) -> int:
    rows = _run(pg.connect(), count_rows_sql(schema, table))
    return int(rows[0][0])


def load_layers(layers: dict, pg: PgConnection, schema: str, *, source="", stats=None,
                overwrite=True, staging_schema=None, run_id=None) -> LoadResult:
    """Load {table name: QgsVectorLayer} into pg/schema. All layers load, or none do.

    stats: optional {table: {"read": n}} so the run log can show how many were quarantined.
    """
    quote_ident(schema)
    staging = staging_schema or f"{schema}_stg"
    quote_ident(staging)
    for table in layers:
        quote_ident(table)
    stats = stats or {}
    run_id = run_id or uuid.uuid4().hex[:12]
    result = LoadResult(run_id=run_id, schema=schema)

    conn = pg.connect()
    try:
        _run(conn, "SELECT 1")
    except LoadError as exc:
        raise LoadError(f"Could not connect to PostgreSQL at {pg.host}:{pg.port}: {exc}") from exc

    if not overwrite:
        existing = [t for t in layers
                    if _run(conn, f"SELECT to_regclass({quote_literal(f'{schema}.{t}')})")[0][0]
                    is not None]
        if existing:
            raise LoadError(f"Tables already exist in '{schema}': {existing}. "
                            "Nothing was changed; enable overwrite to replace them.")

    _run(conn, f"CREATE SCHEMA IF NOT EXISTS {quote_ident(staging)}")
    try:
        for table, layer in layers.items():
            t = quote_ident(table)
            _run(conn, f"DROP TABLE IF EXISTS {quote_ident(staging)}.{t}")
            code, message = QgsVectorLayerExporter.exportLayer(
                layer, pg.data_source(staging, table).uri(False), "postgres", layer.crs(),
                False, {"overwrite": True})
            if not _export_ok(code):
                raise LoadError(f"Could not stage '{table}': {message}")

            staged = int(_run(conn, count_rows_sql(staging, table))[0][0])
            if staged != layer.featureCount():
                raise LoadError(f"'{table}': staged {staged} rows but expected "
                                f"{layer.featureCount()}.")
            srid = layer.crs().postgisSrid()
            found = {row[0] for row in _run(
                conn, distinct_srid_sql(staging, table, GEOMETRY_COLUMN))}
            if found - {srid}:
                raise LoadError(f"'{table}': stored SRIDs {sorted(found)} differ from {srid}.")
            _run(conn, f"CREATE INDEX {quote_ident(table + '_geom_gix')} ON "
                       f"{quote_ident(staging)}.{t} USING GIST ({GEOMETRY_COLUMN})")
            result.expected[table] = staged

        _run(conn, _swap_sql(schema, staging, result.expected, run_id, source, stats, overwrite))
    except LoadError as exc:
        _drop_staging(conn, staging, layers)
        raise LoadError(f"{exc} The target schema was not changed.") from exc

    _drop_staging(conn, staging, layers)
    for table in layers:
        result.loaded[table] = count_rows(pg, schema, table)
    return result
