import pytest

from geomigrate_qa.core.sqlutil import quote_ident, quote_literal


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
