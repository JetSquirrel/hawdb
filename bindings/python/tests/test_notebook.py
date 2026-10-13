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

"""Notebook HTML display and the optional IPython magics, without Jupyter."""

import os
import subprocess
import sys
import types

import pytest

import hawdb
from hawdb import _display


def _run_fresh(code):
    # A fresh interpreter, because this process has imported `hawdb.magic`;
    # PYTHONPATH carries the test path into it (Bazel sets no site-packages).
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_html_table_lists_columns_and_rows(db):
    db.execute("CREATE (s:Stock {code: $code})", {"code": "603122"})
    html = db.execute("MATCH (s:Stock) RETURN s.code")._repr_html_()
    assert "<th>s.code</th>" in html
    assert "<td>603122</td>" in html
    assert "more row" not in html


def test_html_escapes_text(db):
    db.execute("CREATE (s:Stock {code: $code})", {"code": "<script>x</script>"})
    html = db.execute("MATCH (s:Stock) RETURN s.code")._repr_html_()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_ignores_fetch_cursor(db):
    db.execute("CREATE (s:Stock {code: 'a'})")
    result = db.execute("MATCH (s:Stock) RETURN s.code")
    result.fetchall()
    assert "<td>a</td>" in result._repr_html_()


def test_html_caps_rows_and_notes_omitted(db):
    with db.transaction() as tx:
        for i in range(105):
            tx.execute("CREATE (s:Stock {n: $n})", {"n": i})
    html = db.execute("MATCH (s:Stock) RETURN s.n")._repr_html_()
    assert html.count("<tr>") == 101  # header plus 100 rows
    assert "5 more rows not shown (105 total)" in html


def test_render_html_limit_is_adjustable():
    rows = [{"n": i} for i in range(5)]
    html = _display.render_html(["n"], rows, limit=2)
    assert html.count("<tr>") == 3
    assert "3 more rows not shown (5 total)" in html
    assert "more row" not in _display.render_html(["n"], rows, limit=5)


def test_render_html_counts_rows_beyond_those_passed():
    html = _display.render_html(["n"], [{"n": 0}, {"n": 1}], total=1000, limit=2)
    assert html.count("<tr>") == 3
    assert "998 more rows not shown (1000 total)" in html


def test_html_notes_empty_results(db):
    html = db.execute("MATCH (s:Missing) RETURN s.code")._repr_html_()
    assert html == "<p>(no rows)</p>"
    html = _display.render_html(["s.code"], [])
    assert "<th>s.code</th>" in html
    assert "<p>(no rows)</p>" in html


def test_plain_repr_is_unchanged(db):
    db.execute("CREATE (s:Stock {code: 'a'})")
    assert repr(db.execute("MATCH (s:Stock) RETURN s.code")) == (
        'hawdb.QueryResult(columns=["s.code"], rows=1)'
    )


def test_render_html_formats_null_and_bytes():
    html = _display.render_html(["a", "b"], [{"a": None, "b": b"\x00"}])
    assert "<td>NULL</td>" in html
    assert "<td>b&#x27;\\x00&#x27;</td>" in html


class FakeShell:
    """Mirrors IPython's `magics_manager.magics` layout and counts registrations."""

    def __init__(self):
        self.user_ns = {}
        self.registrations = 0
        self.magics_manager = types.SimpleNamespace(magics={"line": {}, "cell": {}})

    @property
    def magics(self):
        return {
            (kind, name): func
            for kind, table in self.magics_manager.magics.items()
            for name, func in table.items()
        }

    def register_magic_function(self, func, kind, name):
        self.registrations += 1
        self.magics_manager.magics[kind][name] = func


@pytest.fixture
def shell():
    from hawdb import magic

    fake = FakeShell()
    magic.register(fake)
    yield fake
    magic.unregister(fake)


def test_magics_register_names(shell):
    assert set(shell.magics) == {
        ("line", "hawdb"),
        ("cell", "cypher"),
        ("cell", "sql"),
    }


def test_register_is_idempotent_and_unload_cleans_up(shell):
    from hawdb import magic

    magic.register(shell)  # `%load_ext` after the import-time registration
    magic.load_ipython_extension(shell)
    assert shell.registrations == 3

    shell.magics[("line", "hawdb")]("open")
    db = magic._selected
    magic.unload_ipython_extension(shell)
    assert shell.magics == {}
    assert magic._selected is None and magic._shell is None
    with pytest.raises(RuntimeError, match="database is closed"):
        db.execute("MATCH (s:Stock) RETURN s.code")

    magic.load_ipython_extension(shell)  # reload after unload works
    assert len(shell.magics) == 3


def test_close_leaves_notebook_owned_handles_open(shell):
    line = shell.magics[("line", "hawdb")]
    cypher = shell.magics[("cell", "cypher")]
    mine = hawdb.open()
    shell.user_ns["mine"] = mine
    line("use mine")
    line("close")  # forgets the selection, does not close the user's handle
    mine.execute("CREATE (s:Stock {code: 'a'})")

    shell.user_ns["hawdb_db"] = mine
    with pytest.raises(ValueError, match="'hawdb_db' belongs to the notebook"):
        line("close")
    assert cypher("", "MATCH (s:Stock) RETURN s.code").row_count == 1


def test_cypher_cell_uses_namespace_db_and_params(shell):
    db = hawdb.open()
    shell.user_ns["hawdb_db"] = db
    shell.user_ns["params"] = {"code": "603122"}
    cypher = shell.magics[("cell", "cypher")]
    cypher("", "CREATE (s:Stock {code: $code})")
    result = cypher("", "MATCH (s:Stock) RETURN s.code")
    assert result.fetchall() == [{"s.code": "603122"}]


def test_sql_cell_uses_positional_params(shell):
    db = hawdb.open()
    db.execute_sql("CREATE TABLE t (id BIGINT PRIMARY KEY, v BIGINT)")
    shell.user_ns["hawdb_db"] = db
    sql = shell.magics[("cell", "sql")]
    shell.user_ns["params"] = [1, 7]
    sql("", "INSERT INTO t (id, v) VALUES ($1, $2)")
    shell.user_ns["params"] = [1]
    assert sql("", "SELECT v FROM t WHERE id = $1").fetchall() == [{"v": 7}]


def test_magic_line_rejects_any_text(shell):
    shell.user_ns["hawdb_db"] = hawdb.open()
    for kind, magic in (("cypher", "%%cypher"), ("sql", "%%sql")):
        cell = shell.magics[("cell", kind)]
        for line in ("--oops", "--params p", "x"):
            with pytest.raises(ValueError, match=f"{magic} takes no options"):
                cell(line, "MATCH (s:Stock) RETURN s.code")


def test_params_type_mismatch_names_the_variable(shell):
    shell.user_ns["hawdb_db"] = hawdb.open()
    shell.user_ns["params"] = [1]
    with pytest.raises(TypeError, match="%%cypher expects params to be a dict, got list"):
        shell.magics[("cell", "cypher")]("", "MATCH (s:Stock) RETURN s.code")
    shell.user_ns["params"] = {"a": 1}
    with pytest.raises(TypeError, match="%%sql expects params to be a list, got dict"):
        shell.magics[("cell", "sql")]("", "SELECT 1")
    shell.user_ns["params"] = (1,)  # the binding takes only a list
    with pytest.raises(TypeError, match="%%sql expects params to be a list, got tuple"):
        shell.magics[("cell", "sql")]("", "SELECT 1")


def test_hawdb_db_must_be_a_database(shell):
    shell.user_ns["hawdb_db"] = "./graph"
    with pytest.raises(TypeError, match="'hawdb_db' must be a hawdb.Database, got str"):
        shell.magics[("cell", "cypher")]("", "MATCH (s:Stock) RETURN s.code")


def test_line_magic_rejects_extra_arguments(shell):
    line = shell.magics[("line", "hawdb")]
    shell.user_ns["a"] = hawdb.open()
    shell.user_ns["b"] = hawdb.open()
    for text in ("close now", "use", "use a b"):
        with pytest.raises(ValueError, match="usage: %hawdb"):
            line(text)


def test_line_magic_open_use_close(shell):
    line = shell.magics[("line", "hawdb")]
    cypher = shell.magics[("cell", "cypher")]
    line("open")
    cypher("", "CREATE (s:Stock {code: 'a'})")
    assert cypher("", "MATCH (s:Stock) RETURN s.code").row_count == 1
    line("close")
    with pytest.raises(RuntimeError, match="no HawDB database selected"):
        cypher("", "MATCH (s:Stock) RETURN s.code")
    shell.user_ns["mine"] = hawdb.open()
    line("use mine")
    cypher("", "CREATE (s:Stock {code: 'b'})")
    assert cypher("", "MATCH (s:Stock) RETURN s.code").fetchall() == [{"s.code": "b"}]
    with pytest.raises(ValueError):
        line("use missing")
    with pytest.raises(ValueError):
        line("bogus")


def test_failed_open_keeps_the_current_selection(shell, tmp_path):
    line = shell.magics[("line", "hawdb")]
    cypher = shell.magics[("cell", "cypher")]
    line("open")
    cypher("", "CREATE (s:Stock {code: 'a'})")
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    with pytest.raises(hawdb.exceptions.Error):
        line(f"open {not_a_dir / 'graph'}")
    assert cypher("", "MATCH (s:Stock) RETURN s.code").row_count == 1


def test_open_strips_one_pair_of_quotes(shell, tmp_path):
    line = shell.magics[("line", "hawdb")]
    cypher = shell.magics[("cell", "cypher")]
    path = tmp_path / "my graph"
    line(f'open "{path}"')
    cypher("", "CREATE (s:Stock {code: 'a'})")
    line("close")
    line(f"open '{path}'")
    assert cypher("", "MATCH (s:Stock) RETURN s.code").row_count == 1
    assert not (tmp_path / '"my graph"').exists()


def test_unquote_leaves_backslashes_and_unmatched_quotes():
    from hawdb import magic

    assert magic._unquote(r'"C:\data\graph"') == r"C:\data\graph"
    assert magic._unquote(r"C:\data\graph") == r"C:\data\graph"
    assert magic._unquote("\"graph'") == "\"graph'"
    assert magic._unquote('"') == '"'


def test_import_without_ipython_does_not_import_it():
    code = (
        "import sys, hawdb, hawdb.magic; "
        "assert 'IPython' not in sys.modules"
    )
    _run_fresh(code)


def test_attribute_access_does_not_load_magics():
    code = (
        "import sys, hawdb; "
        "assert not hasattr(hawdb, 'magic'); "
        "assert 'hawdb.magic' not in sys.modules"
    )
    _run_fresh(code)
