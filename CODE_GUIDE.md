# Code Guide

This guide explains what each file does and what each function is responsible for. It's meant for reading the code, not for running it. For installation and usage, see `README.md`.

## Files

| File | Purpose |
|---|---|
| `invoice_generator.py` | The main program: loading, validation, totals, PDF rendering, and the command line |
| `test_invoice_generator.py` | Automated tests for the math and the validation rules |
| `benchmark.py` | Creates a large fake dataset and measures how long the generator takes |
| `data/clients.csv` | Sample clients |
| `data/line_items.csv` | Sample invoices and line items |
| `clients.csv`, `line_items.csv` | A larger sample (20 clients, 40 invoices) |
| `line_items_with_errors.csv` | Rows with deliberate mistakes, to show the error report |
| `requirements.txt` | The Python libraries the project needs (`reportlab`) |
| `README.md` | Project overview and instructions |

---

## `invoice_generator.py`

The file is organized in four sections: imports and constants, data classes, loading and validation, and rendering. The command line is at the bottom.

### Imports and constants

- `csv` reads and writes CSV files.
- `Decimal` stores money exactly. Python's `float` can't represent `0.10` precisely, so `0.1 + 0.2` gives `0.30000000000000004`. `Decimal` avoids this.
- `ROUND_HALF_UP` makes `.5` round up (`1.005` becomes `1.01`), which is the rounding most people expect on invoices.
- `CENT = Decimal("0.01")` is the smallest unit used for rounding.
- `SAFE_ID` is a regular expression (a text pattern) that only allows letters, numbers, `-` and `_` in IDs. This keeps IDs safe to use as file names.
- `CLIENT_COLUMNS` and `ITEM_COLUMNS` list the columns each CSV must have.
- `reportlab` is the PDF library. Its `Paragraph`, `Table`, and `SimpleDocTemplate` classes do the layout.

### Data classes

A data class is a small class that holds related values. The `@dataclass` line at the top generates the setup code automatically.

- **`Client`** holds `client_id`, `name`, `email`, and `address`. `frozen=True` means its values can't change after creation.
- **`LineItem`** holds one row: `description`, `quantity`, and `unit_price`.
  - The `amount` property is a calculated value. It multiplies quantity by price and rounds to the cent. A property is read like an attribute (`item.amount`) but is computed each time.
- **`Invoice`** holds the invoice ID, the client, the dates, and a list of line items.
  - `subtotal` adds up the amount of every line. The second argument to `sum()` is the starting value, `Decimal("0.00")`, so the result stays a `Decimal`.
  - `tax(rate)` returns the tax for a given rate, rounded to the cent.

### Loading and validation

**`_cell(row, key)`** gets one cell from a CSV row, returns an empty string if it's missing, and removes surrounding spaces.

**`_check_columns(path, fieldnames, required)`** stops the program with a clear message if the CSV is missing a required column. This catches a wrong header before any rows are processed.

**`_parse_decimal(text, name)`** converts text to a `Decimal`. It raises a `ValueError` with the field name if the text isn't a number, or if it's `NaN` or infinity.

**`format_percent(rate)`** turns a tax rate back into the percent printed on the invoice, without rounding: `0.075` becomes `7.5`, `0.10` becomes `10`. `normalize()` removes trailing zeros.

**`_parse_date(text, name)`** converts a `YYYY-MM-DD` string to a `date`. `date.fromisoformat` does the work, and a clear error message is raised if the format is wrong.

**`load_clients(path)`** reads `clients.csv` into a dictionary (`client_id` → `Client`). It returns two things: the dictionary and a list of error messages. Errors for invalid IDs, duplicate IDs, and missing names are collected rather than raised, so every problem is reported in one run.

**`load_items(path, clients)`** is the most important validation function. It reads each line item row and:
1. Checks each field, raising `ValueError` with a message if something is wrong.
2. If the row is bad, it records the error and adds the `invoice_id` to a `rejected` set. The `continue` skips the rest of the loop body for that row.
3. If the row is good, it creates the invoice on first sight, or adds the line to the existing invoice.
4. If a later row disagrees with the invoice's client or dates, the invoice is rejected.
5. At the end, every rejected invoice is removed from the results.

The `try` / `except ValueError` block is how the code handles bad input: an error in one row is caught instead of crashing the whole run. The `enumerate(reader, start=2)` gives line numbers that match the spreadsheet, starting at 2 because line 1 is the header.

**`build_invoices(clients_path, items_path)`** is a simple wrapper that loads both files and returns the invoices sorted by ID, plus all errors.

### Rendering

**`render_pdf(invoice, out_dir, ...)`** builds one PDF:
- `SimpleDocTemplate` creates an A4 page with margins.
- `story` is a list of elements (text, spacing, the table) that ReportLab lays out top to bottom.
- `Paragraph` displays wrapped text. `escape()` converts characters like `&` and `<` into safe text, so a client name like "Smith & Sons" doesn't break the PDF.
- The table rows are built from the line items. Then three summary rows (subtotal, tax, total) are added.
- `TableStyle` controls colors, alignment, and lines. The row numbers in these commands are counted from the bottom (`n - 4`, `n - 3`), so the lines land correctly regardless of how many items there are.

**`generate_pdfs(invoices, out_dir, ...)`** calls `render_pdf` for each invoice. It also writes `summary.csv`, which has one row per invoice. `mkdir(parents=True, exist_ok=True)` creates the output folder if it doesn't exist.

### Command line

**`main(argv)`** runs everything:
- `argparse` defines the options (`--clients`, `--items`, `--out`, `--company`, `--tax-percent`, `--currency`) and handles `--help` automatically.
- The tax percent is converted to a rate: `10` becomes `Decimal("0.10")`.
- `time.perf_counter()` measures how long the run takes.
- The function returns `0` on success, `1` if some rows were skipped, and `2` if a file couldn't be read.

The last two lines, `if __name__ == "__main__": sys.exit(main())`, run `main()` only when the file is started directly. This lets the tests import the functions without running the program.

---

## `test_invoice_generator.py`

Uses Python's built-in `unittest` library. Each test is a method whose name starts with `test_`.

- **`item_row(...)`** builds one CSV line with defaults, so each test only specifies the field it's testing.
- **`build_from_text(item_lines)`** writes temporary CSV files, runs the loader on them, and deletes the files. Tests don't need real data on disk.
- **`MathTests`** checks the calculations. The rounding test confirms that `1.005` rounds to `1.01`, not `1.00`, and the tax label test confirms 7.5% isn't shown as 8%.
- **`ValidationTests`** checks each rule: a bad row drops its whole invoice but not other invoices, unknown clients are rejected, due dates can't be before issue dates, unsafe IDs like `../etc/passwd` are rejected, and so on.

---

## `benchmark.py`

Measures performance so the README claims come from real runs.

- **`make_dataset(folder, invoices, clients, seed)`** writes random clients and invoices to temporary CSV files. `random.Random(seed)` uses a fixed seed, so every run creates the same data and results are repeatable.
- **`main()`** runs the real `build_invoices` and `generate_pdfs` functions several times and reports the median time. The median is less affected by one slow run than the average.
- `perf_counter()` is a high-resolution timer, suitable for measuring short durations.

---

## Key ideas to know

- **Validate before calculating.** Bad data is caught at the boundary, so the math code can assume its inputs are correct.
- **Use `Decimal` for money.** Never use `float` for currency.
- **Collect errors instead of stopping.** One run reports every problem, which is faster to fix.
- **Separate logic from output.** Loading, calculating, and rendering are separate functions, so each can be tested or changed alone.
- **Tests and benchmarks are part of the project.** They show the code is checked, and they back up the numbers in the README.
