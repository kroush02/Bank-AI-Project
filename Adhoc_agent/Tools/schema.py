"""Only schema and business definitions go to Gemini, never database rows."""

SCHEMA_SQL = """
CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    city TEXT NOT NULL,
    segment TEXT NOT NULL CHECK (segment IN ('retail', 'business')),
    created_at TEXT NOT NULL
);
CREATE TABLE "transaction" (
    transaction_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(customer_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL CHECK (currency IN ('EGP', 'USD')),
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('credit', 'debit')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'failed')),
    transaction_date TEXT NOT NULL
);
CREATE INDEX idx_transaction_customer_date ON "transaction" (customer_id, transaction_date);
"""

TABLE_COLUMNS = {
    "customer": {"customer_id", "full_name", "city", "segment", "created_at"},
    "transaction": {
        "transaction_id",
        "customer_id",
        "amount_minor",
        "currency",
        "transaction_type",
        "status",
        "transaction_date",
    },
}

SCHEMA_CONTEXT = (
    SCHEMA_SQL
    + """
SQLite dialect. Exactly two permitted tables: customer and "transaction".
Join customer.customer_id = "transaction".customer_id.
Quote the reserved table name "transaction"; explicit aliases are recommended.
Money is stored as nonnegative integer minor units (100 minor units = 1 EGP or USD).
Keep currencies separate; there are no FX rates and currencies cannot be added together.
Credits and debits are separate categories, not signed balance movements.
There is no balance, account number, email, phone, or account table.
Dates use ISO YYYY-MM-DD, UTC date, and month filters use inclusive start / exclusive end.
Default transaction totals include status='completed'; never include failed/pending by accident.
"""
)
