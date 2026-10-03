"""Deterministic SQL policy and a second enforcement layer inside SQLite."""

import sqlite3
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from Adhoc_agent.models import SQLPlan, WorkflowError

from .database import open_readonly
from .schema import TABLE_COLUMNS

SQL_FUNCTIONS = {
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "ROUND",
    "COALESCE",
    "ABS",
    "LOWER",
    "UPPER",
    "LENGTH",
    "DATE",
    "STRFTIME",
    "IFNULL",
    "NULLIF",
    # SQLGlot's names for the corresponding SQLite functions.
    "TIME_TO_STR",
    "TS_OR_DS_TO_DATE",
    "TS_OR_DS_TO_TIMESTAMP",
}
SQLITE_FUNCTIONS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "round",
    "coalesce",
    "abs",
    "lower",
    "upper",
    "length",
    "date",
    "strftime",
    "ifnull",
    "nullif",
}


def conjuncts(node):
    if isinstance(node, exp.Paren):
        yield from conjuncts(node.this)
    elif isinstance(node, exp.And):
        yield from conjuncts(node.this)
        yield from conjuncts(node.expression)
    elif node is not None:
        yield node


def validate_sql(plan: SQLPlan) -> None:
    try:
        statements = sqlglot.parse(plan.sql, read="sqlite")
    except ParseError as exc:
        raise WorkflowError("SQL could not be parsed.") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise WorkflowError("Only one SELECT statement is permitted.")
    tree = statements[0]
    if (
        any(
            tree.find(kind) is not None
            for kind in (
                exp.Subquery,
                exp.CTE,
                exp.Union,
                exp.Window,
                exp.Into,
            )
        )
        or sum(isinstance(n, exp.Select) for n in tree.walk()) != 1
    ):
        raise WorkflowError("Subqueries, CTEs, unions, windows and SELECT INTO are unsupported.")
    tables = list(tree.find_all(exp.Table))
    if not 1 <= len(tables) <= 2:
        raise WorkflowError("Query must use one or both bank tables.")
    if any(t.name.lower() not in TABLE_COLUMNS or t.db or t.catalog for t in tables):
        raise WorkflowError("Query references a table outside the approved schema.")
    aliases = {t.alias_or_name.lower(): t.name.lower() for t in tables}
    if len(aliases) != len(tables) or len({t.name.lower() for t in tables}) != len(tables):
        raise WorkflowError("Duplicate table names or aliases are unsupported.")
    output_aliases = {e.alias.lower() for e in tree.expressions if e.alias}
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if column.table:
            table = aliases.get(column.table.lower())
            if table is None or name not in TABLE_COLUMNS[table] or column.db or column.catalog:
                raise WorkflowError("Unknown or unapproved SQL column.")
        elif name not in output_aliases:
            matches = sum(name in TABLE_COLUMNS[t] for t in aliases.values())
            if matches != 1:
                raise WorkflowError(
                    "Unknown or ambiguous SQL column; qualify it with a table alias."
                )
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise WorkflowError("Select explicit columns; only COUNT(*) may use a wildcard.")
    for func in tree.find_all(exp.Func):
        if isinstance(func, (exp.Connector, exp.Case, exp.If)):
            continue
        name = func.name.upper() if isinstance(func, exp.Anonymous) else func.sql_name()
        if name not in SQL_FUNCTIONS:
            raise WorkflowError(f"SQL function {name} is not permitted.")
    joins = list(tree.find_all(exp.Join))
    if len(tables) == 2 and len(joins) != 1:
        raise WorkflowError("Use one explicit customer/transaction join.")
    for join in joins:
        if (
            join.args.get("side") not in {None, "", "LEFT"}
            or join.args.get("kind") not in {None, "", "INNER"}
            or join.args.get("method")
            or join.args.get("using")
            or not join.args.get("on")
        ):
            raise WorkflowError("Only explicit INNER or LEFT joins with ON are supported.")
        # Only top-level AND conjuncts guarantee that the FK relation is mandatory.
        predicates = list(conjuncts(join.args["on"]))
        valid_fk = False
        for predicate in predicates:
            if isinstance(predicate, exp.EQ):
                pair = [predicate.this, predicate.expression]
                if all(isinstance(c, exp.Column) and c.name.lower() == "customer_id" for c in pair):
                    names = {aliases.get(c.table.lower()) for c in pair}
                    valid_fk |= names == {"customer", "transaction"}
        if not valid_fk:
            raise WorkflowError("Join must require customer.customer_id = transaction.customer_id.")
    money_aggregates = [
        f
        for f in tree.find_all(exp.AggFunc)
        if isinstance(f, (exp.Sum, exp.Avg))
        and any(c.name.lower() == "amount_minor" for c in f.find_all(exp.Column))
    ]
    if money_aggregates:
        group = tree.args.get("group")
        grouped_currency = group is not None and any(
            isinstance(e, exp.Column) and e.name.lower() == "currency" for e in group.expressions
        )
        conditions = list(conjuncts(tree.args.get("where").this)) if tree.args.get("where") else []
        for join in joins:
            conditions.extend(conjuncts(join.args.get("on")))
        fixed_currency = False
        for predicate in conditions:
            if not isinstance(predicate, exp.EQ):
                continue
            for column, value in (
                (predicate.this, predicate.expression),
                (predicate.expression, predicate.this),
            ):
                if not isinstance(column, exp.Column) or column.name.lower() != "currency":
                    continue
                bound = (
                    plan.bindings().get(value.name)
                    if isinstance(value, exp.Placeholder)
                    else value.this
                    if isinstance(value, exp.Literal) and value.is_string
                    else None
                )
                fixed_currency |= bound in {"EGP", "USD"}
        if not grouped_currency and not fixed_currency:
            raise WorkflowError("Monetary totals must group by currency or filter one currency.")
    placeholders = {p.name for p in tree.find_all(exp.Placeholder)}
    if "" in placeholders or placeholders != set(plan.bindings()):
        raise WorkflowError("Named SQL parameters must exactly match the supplied bindings.")


def authorizer(action, first, second, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if (
            (database == "main" or (database is None and not second))
            and first in TABLE_COLUMNS
            and (not second or second in TABLE_COLUMNS[first])
        ):
            return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in SQLITE_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def prepare_connection(path: Path):
    conn = open_readonly(path)
    conn.set_authorizer(authorizer)
    return conn


def check_query_compiles(path: Path, plan: SQLPlan):
    conn = prepare_connection(path)
    try:
        conn.execute("EXPLAIN QUERY PLAN " + plan.sql, plan.bindings()).fetchall()
    except sqlite3.Error as exc:
        raise WorkflowError("SQL does not compile against the allowed schema: " + str(exc)) from exc
    finally:
        conn.close()
