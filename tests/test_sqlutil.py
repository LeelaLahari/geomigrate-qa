import pytest

from geomigrate_qa.core.sqlutil import (
    count_rows_sql,
    distinct_srid_sql,
    qualified,
    quote_ident,
    quote_literal,
    run_log_insert_sql,
)


def test_valid_identifiers_are_quoted():
    assert quote_ident("poles") == '"poles"'
    assert quote_ident("_stg_2") == '"_stg_2"'


@pytest.mark.parametrize("bad", ["", "1abc", "has space", 'a"b', "x;DROP TABLE y", "a-b",
                                 "a" * 64, None, 5])
def test_bad_identifiers_are_refused(bad):
    with pytest.raises(ValueError):
        quote_ident(bad)


def test_literals_are_escaped():
    assert quote_literal("it's") == "'it''s'"
    assert quote_literal("x'); DROP TABLE t; --") == "'x''); DROP TABLE t; --'"
    assert quote_literal(None) == "NULL"
    assert quote_literal(3) == "3"
    assert quote_literal(2.5) == "2.5"
    assert quote_literal(True) == "TRUE"


def test_unstorable_values_are_refused():
    with pytest.raises(ValueError):
        quote_literal(float("nan"))
    with pytest.raises(ValueError):
        quote_literal("a\x00b")


def test_query_builders_produce_the_expected_sql():
    assert qualified("demo", "poles") == '"demo"."poles"'
    assert count_rows_sql("demo", "poles") == 'SELECT count(*) FROM "demo"."poles"'
    assert distinct_srid_sql("demo_stg", "poles") == (
        'SELECT DISTINCT ST_SRID("geom") FROM "demo_stg"."poles" WHERE "geom" IS NOT NULL')


def test_query_builders_refuse_unsafe_names():
    with pytest.raises(ValueError):
        count_rows_sql("demo", 'poles"; DROP TABLE x; --')
    with pytest.raises(ValueError):
        distinct_srid_sql("demo", "poles", "geom; --")


def test_log_insert_escapes_values_and_does_not_expand_dollars():
    sql = run_log_insert_sql("demo", "geomigrate_run_log", "abc123", "x'); DROP TABLE t; --",
                             "poles", 48, 35, 13, "loaded")
    assert sql.startswith('INSERT INTO "demo"."geomigrate_run_log"')
    assert "'x''); DROP TABLE t; --'" in sql and "48, 35, 13, 'loaded'" in sql
    dollars = run_log_insert_sql("demo", "geomigrate_run_log", "r", "$log $v_run", "t", 1, 1, 0, "ok")
    assert "'$log $v_run'" in dollars


def test_log_insert_only_accepts_numbers_for_counts():
    with pytest.raises(ValueError):
        run_log_insert_sql("demo", "log", "r", "s", "t", "1; DROP TABLE x", 1, 0, "ok")
