"""Tests for totals and validation. Run with: python -m unittest -v"""
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from invoice_generator import Client, Invoice, LineItem, build_invoices, format_percent

CLIENTS_CSV = "client_id,name,email,address\nC001,Acme,a@example.com,Somewhere\n"
ITEMS_HEADER = "invoice_id,client_id,issue_date,due_date,description,quantity,unit_price"


def item_row(
    inv="INV-1", client="C001", issue="2026-01-01", due="2026-01-31",
    desc="Work", qty="1", price="10.00",
):
    return f"{inv},{client},{issue},{due},{desc},{qty},{price}"


def build_from_text(item_lines):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "clients.csv").write_text(CLIENTS_CSV, encoding="utf-8")
        (tmp / "items.csv").write_text(ITEMS_HEADER + "\n" + "\n".join(item_lines) + "\n", encoding="utf-8")
        return build_invoices(tmp / "clients.csv", tmp / "items.csv")


class MathTests(unittest.TestCase):
    def test_line_amount_rounds_half_up(self):
        # 3 x 0.335 = 1.005, which must round to 1.01 (not banker's rounding to 1.00)
        self.assertEqual(LineItem("x", Decimal("3"), Decimal("0.335")).amount, Decimal("1.01"))

    def test_subtotal_tax_and_total(self):
        client = Client("C1", "A", "a@example.com", "somewhere")
        invoice = Invoice("INV-1", client, date(2026, 1, 1), date(2026, 1, 31), [
            LineItem("a", Decimal("1"), Decimal("100.00")),
            LineItem("b", Decimal("1"), Decimal("50.00")),
        ])
        self.assertEqual(invoice.subtotal, Decimal("150.00"))
        self.assertEqual(invoice.tax(Decimal("0.10")), Decimal("15.00"))
        self.assertEqual(invoice.subtotal + invoice.tax(Decimal("0.10")), Decimal("165.00"))

    def test_tax_percent_label_is_not_rounded(self):
        # A 7.5% rate must be shown as 7.5%, not rounded to 8%
        self.assertEqual(format_percent(Decimal("7.5") / 100), "7.5")
        self.assertEqual(format_percent(Decimal("10") / 100), "10")
        self.assertEqual(format_percent(Decimal("0")), "0")


class ValidationTests(unittest.TestCase):
    def test_valid_invoice_is_built(self):
        invoices, errors = build_from_text([item_row(qty="2", price="10.00"), item_row(desc="More", price="5.00")])
        self.assertEqual(errors, [])
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].subtotal, Decimal("25.00"))

    def test_bad_row_skips_whole_invoice_but_not_others(self):
        invoices, errors = build_from_text([
            item_row(inv="INV-1", qty="abc"),          # line 2: bad number
            item_row(inv="INV-1", desc="More"),        # same invoice, valid, but must be dropped too
            item_row(inv="INV-2"),                     # unrelated, must survive
        ])
        self.assertEqual([i.invoice_id for i in invoices], ["INV-2"])
        self.assertEqual(len(errors), 1)
        self.assertIn("line 2", errors[0])

    def test_unknown_client_is_rejected(self):
        invoices, errors = build_from_text([item_row(client="C999")])
        self.assertEqual(invoices, [])
        self.assertIn("unknown client_id", errors[0])

    def test_due_date_before_issue_date_is_rejected(self):
        invoices, errors = build_from_text([item_row(issue="2026-02-01", due="2026-01-01")])
        self.assertEqual(invoices, [])
        self.assertIn("due_date is before issue_date", errors[0])

    def test_unsafe_invoice_id_is_rejected(self):
        invoices, errors = build_from_text([item_row(inv="../etc/passwd")])
        self.assertEqual(invoices, [])
        self.assertIn("invalid invoice_id", errors[0])

    def test_zero_quantity_and_negative_price_are_rejected(self):
        _, errors = build_from_text([item_row(inv="INV-1", qty="0"), item_row(inv="INV-2", price="-1")])
        self.assertEqual(len(errors), 2)

    def test_lines_with_different_dates_for_one_invoice_are_rejected(self):
        invoices, errors = build_from_text([item_row(), item_row(issue="2026-01-02")])
        self.assertEqual(invoices, [])
        self.assertIn("differ", errors[0])

    def test_missing_column_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "clients.csv").write_text(CLIENTS_CSV, encoding="utf-8")
            (tmp / "items.csv").write_text("invoice_id,client_id\nINV-1,C001\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                build_invoices(tmp / "clients.csv", tmp / "items.csv")
            self.assertIn("missing required column", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
