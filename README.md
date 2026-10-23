# Invoice Generator

A Python command-line tool that turns two CSV files (clients and line items) into one formatted PDF invoice per invoice, plus a summary CSV. It validates every row first, so a typo never produces a wrong total.

## Results

Measured with `benchmark.py` on synthetic data (500 invoices, 2,263 line items, 50 clients; median of 3 runs) on Linux x86_64, Python 3.13:

| Step | Time |
|---|---|
| Parse, validate, calculate totals | 0.014 s |
| Render 500 PDFs + summary CSV | 2.08 s |
| **Total** | **2.1 s (about 240 invoices/s)** |

Scaling check: 2,000 invoices (8,932 line items) took 8.7 s, about the same rate, so time grows linearly with volume.

**Manual baseline:** _[fill in: time yourself creating 10 invoices by hand in Word or Excel, then divide by 10 to get minutes per invoice. Example: "Manual: about 6 minutes per invoice, so 500 invoices would take about 50 hours. Script: 2.1 seconds."]_

Test coverage: 11 unit tests covering rounding, totals, the tax label, and each validation rule (`python -m unittest -v`).

## Why it's useful

Writing invoices by hand in Word or Excel is slow and error-prone: copy-paste mistakes, a wrong total, a missed line. This tool is useful for:

- **Freelancers and small businesses** who bill many clients each month and already track work in a spreadsheet.
- **Monthly or batch billing**: export your hours or sales to CSV, run one command, get every invoice.
- **Accounting**: `summary.csv` gives your bookkeeper (or your own spreadsheet) every invoice's totals in one place.
- **Accuracy**: totals use exact decimal math, and a broken row stops that invoice instead of producing a wrong one.

## Features

- Groups line items into invoices by `invoice_id`
- Calculates line amounts, subtotal, tax, and total using `Decimal` (no floating-point rounding errors) with half-up rounding to the cent
- Validates every row: IDs, known clients, numbers, quantities, prices, dates, and due date after issue date
- If any row in an invoice is invalid, that whole invoice is skipped and the error is reported with its line number. A partial invoice would have a wrong total.
- Renders a clean A4 PDF per invoice (company name, bill-to block, itemized table, tax, total)
- Writes `summary.csv` with every invoice's totals for your accounting records

## How it works

The program runs in four steps:

1. **Load clients.** `clients.csv` is read into a lookup table keyed by `client_id`. Each row is checked for a valid ID, a name, and no duplicates.
2. **Load line items and group them.** Each row of `line_items.csv` is checked: the client must exist, quantity must be above 0, price cannot be negative, and dates must make sense. Valid rows are grouped by `invoice_id`. If any row in an invoice is invalid, the whole invoice is dropped, so a total is never calculated from incomplete data.
3. **Calculate totals.** For each line, `amount = quantity x unit_price`, rounded to the cent. The subtotal is the sum of the line amounts. Tax is the subtotal multiplied by the tax rate, and the total is subtotal plus tax. All money math uses Python's `Decimal` type, which avoids the rounding errors that `float` causes.
4. **Render.** Each invoice becomes a one-page A4 PDF named after its `invoice_id`, such as `INV-001.pdf`. A `summary.csv` with every invoice's totals is written alongside them.

Errors don't stop the run. Every problem is collected, printed with its file and line number, and the program exits with status 1 so you know something was skipped.

For a more detailed walkthrough of each function in the code, see `CODE_GUIDE.md`.

## Requirements

- Python 3.10+
- `reportlab` (see `requirements.txt`)

On newer Linux systems (such as Ubuntu 23.04 and later), the system Python blocks `pip install`. Use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run `source .venv/bin/activate` again each time you open a new terminal.

## Running it each time

The setup above (creating `.venv` and installing `reportlab`) is done once. After that, every run is the same few steps:

1. **Open a terminal in the project folder.**
   ```bash
   cd "/path/to/invoice-generator"
   ```
2. **Activate the virtual environment.** Your prompt will show `(.venv)` when it's active.
   ```bash
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```
3. **Update your input files.** Put this batch's clients and line items in `clients.csv` and `line_items.csv` (see [Input format](#input-format) for how to build them).
4. **Run the generator.**
   ```bash
   python invoice_generator.py --clients clients.csv --items line_items.csv \
     --out output --company "Your Company" --tax-percent 10 --currency USD
   ```
5. **Read the terminal output.** `Generated N invoice(s) ...` with no problem list means every invoice was created. If problems are listed, fix those lines in your CSV and run step 4 again.
6. **Collect the results** from the `output/` folder: one PDF per invoice plus `summary.csv`.
7. **When you're done**, you can leave the virtual environment with `deactivate` (optional).

Each run overwrites `summary.csv` and any PDF with the same invoice ID. PDFs from earlier runs are not deleted, so use a new folder per batch if you want to keep them apart, for example `--out output/2026-10`.

To see what error reporting looks like, run it against the included file with deliberate mistakes: `--items line_items_with_errors.csv`.

## Usage

```bash
python invoice_generator.py \
  --clients data/clients.csv \
  --items data/line_items.csv \
  --out output \
  --company "Your Company" \
  --tax-percent 10 \
  --currency USD
```

| Option | Required | Default | Meaning |
|---|---|---|---|
| `--clients` | yes | | Path to your clients CSV |
| `--items` | yes | | Path to your line items CSV |
| `--out` | no | `output` | Folder for the PDFs and `summary.csv` (created if missing) |
| `--company` | no | `Your Company` | Company name printed on each invoice |
| `--tax-percent` | no | `0` | Tax rate as a percent, such as `10` for 10% |
| `--currency` | no | `USD` | Currency label printed on each invoice |

Exit status: `0` all invoices generated, `1` some invoices skipped because of bad rows, `2` a file could not be read or is missing a required column.

Sample output for the included data:

```
Generated 3 invoice(s) in 0.02 s -> output/
```

`summary.csv`:

```
invoice_id,client,issue_date,due_date,subtotal,tax,total
INV-001,Acme Ltd,2026-10-01,2026-10-31,1440.00,144.00,1584.00
INV-002,Brightline Studio,2026-10-05,2026-11-04,441.00,44.10,485.10
INV-003,Northwind Traders,2026-10-10,2026-10-25,520.00,52.00,572.00
```

If there are errors, the tool prints each one and exits with status 1:

```
Generated 1 invoice(s) in 0.01 s -> output/

6 problem(s) found. Invoices with a bad row were skipped:
  - line_items_with_errors.csv line 3: quantity is not a number: 'two'
  - line_items_with_errors.csv line 4: unknown client_id 'C999'
  - line_items_with_errors.csv line 5: due_date is before issue_date
  - line_items_with_errors.csv line 6: description is empty
  - line_items_with_errors.csv line 7: quantity must be greater than 0
  - line_items_with_errors.csv line 8: unit_price cannot be negative
```

(This is the real output of `--clients clients.csv --items line_items_with_errors.csv`. Only `INV-907` is valid, so only one PDF is made.)

## Input format

You need two CSV files: one listing your clients and one listing every line of every invoice. They can live anywhere, since you pass their paths with `--clients` and `--items`. The easiest start is to copy the samples in `data/` and edit them in Excel, Google Sheets, LibreOffice, or a text editor.

### Step 1: Create `clients.csv`

One row per client. The first line must be this header, exactly:

```
client_id,name,email,address
```

Then add your clients:

```
client_id,name,email,address
C001,Acme Ltd,billing@acme.example,"12 Market Street, Anytown"
C002,Brightline Studio,accounts@brightline.example,"4 Harbour Road, Anytown"
```

- `client_id` is a short code you choose (such as `C001`). Each client needs a different one.
- `email` and `address` columns must be present, but a value can be left blank.

### Step 2: Create `line_items.csv`

One row per line on an invoice. An invoice with three items is three rows that share the same `invoice_id`. The first line must be this header, exactly:

```
invoice_id,client_id,issue_date,due_date,description,quantity,unit_price
```

Then add your items:

```
invoice_id,client_id,issue_date,due_date,description,quantity,unit_price
INV-001,C001,2026-10-01,2026-10-31,Website design,1,1200.00
INV-001,C001,2026-10-01,2026-10-31,Hosting (12 months),1,240.00
INV-002,C002,2026-10-05,2026-11-04,Consulting hours,6.5,80.00
```

- `client_id` must match a client in `clients.csv`.
- Every row of the same invoice must have the same `client_id`, `issue_date` and `due_date`.
- `invoice_id` becomes the PDF file name (`INV-001` becomes `INV-001.pdf`).

### Step 3: Check the formatting before you run

- Save as **CSV UTF-8**. In Excel: File > Save As > "CSV UTF-8 (Comma delimited)".
- Header names are lowercase and spelled exactly as above. Column order doesn't matter, and extra columns are ignored.
- Put double quotes around any value that contains a comma, such as an address. Spreadsheet programs do this for you when saving as CSV.
- Write numbers plainly: `1200.00`, not `$1,200.00`.
- Write dates as `YYYY-MM-DD`, such as `2026-10-01`. Spreadsheets sometimes change dates to `10/01/2026` on save, so check the file if you get date errors.
- IDs may only use letters, numbers, `-` and `_`. No spaces or `/`.

### Step 4: Run and fix any reported rows

Run the command from [Running it each time](#running-it-each-time). Each problem is reported with its file and line number (line 1 is the header), so you can go straight to the row, fix it, and run again.

### Column reference

**clients.csv**

| Column | Notes |
|---|---|
| `client_id` | Unique. Letters, numbers, `-` and `_` only. |
| `name` | Required. |
| `email` | Shown on the invoice. |
| `address` | Shown on the invoice. |

**line_items.csv**

| Column | Notes |
|---|---|
| `invoice_id` | Groups rows into one invoice. Same rules as `client_id`. |
| `client_id` | Must exist in `clients.csv`. |
| `issue_date`, `due_date` | `YYYY-MM-DD`. Due date cannot be before issue date. All rows of an invoice must share the same client and dates. |
| `description` | Required. |
| `quantity` | Greater than 0. Decimals allowed (for example `6.5` hours). |
| `unit_price` | 0 or more. |

## Benchmark

```bash
python benchmark.py --invoices 500 --repeat 3
```

Run this on your own machine. The results depend on your hardware, so use your own numbers in any claim.

`benchmark.py` is a speed test for the invoice generator. It makes a big batch of fake invoice data, runs the real code on it, and reports how long the run took.

**What it does**

1. **Makes fake data** (`make_dataset`, lines 32–57). In a temporary folder it writes a `clients.csv` (50 clients by default) and a `line_items.csv` (500 invoices by default). Each invoice gets 1–8 random line items like "Hosting" or "SEO audit", with random quantities, prices and dates in 2026. It uses a fixed random seed (`--seed 42`), so every run produces exactly the same data and results can be compared.
2. **Runs the real pipeline** (`main`, lines 60–98). It calls the same two functions the app uses, from `invoice_generator.py`:
   - `build_invoices(...)` reads the CSVs, validates the rows and calculates totals. This part is timed as "parse".
   - `generate_pdfs(...)` creates the actual PDF files. This part is timed as "render".

   It does this 3 times by default (`--repeat`) using `perf_counter`. If the fake data ever fails validation, it stops with an error, because that would point to a bug.
3. **Reports results.** It prints your machine and Python version, the dataset size, the median time for each stage, the total time with its min and max, and throughput in invoices per second. It uses the median rather than the average so one slow run doesn't skew the result. The temporary folder is deleted automatically afterwards, so nothing is left in the project.

**Why it matters in this project**

- **It backs up the README's numbers.** The performance table in [Results](#results) ("2.1 s, about 240 invoices/s" for 500 invoices) comes from this script. `CODE_GUIDE.md` says its purpose is so "the README claims come from real runs." Anyone can rerun it and check those numbers.
- **It shows how the app scales.** The check that 2,000 invoices took about 8.7 s at the same rate shows the time grows linearly, so you can estimate how long a big batch will take.
- **It shows where the time goes.** Splitting parse from render tells you which stage to optimize. PDF rendering with reportlab is almost certainly the slow part.
- **It catches slowdowns.** Run it before and after changing `invoice_generator.py` to see if the change made things slower.
- **It's portfolio evidence.** Together with `test_invoice_generator.py`, it shows the project is both tested and measured.

## Tests

```bash
python -m unittest -v
```

`test_invoice_generator.py` is the project's automated test suite. It checks that `invoice_generator.py` does the money math correctly and rejects bad CSV data, so you can change the code later and know right away if something broke. All 11 tests pass.

This uses Python's built-in `unittest` module, so nothing extra needs installing. The `-v` flag prints each test's name and whether it passed.

**How it works**

The real program reads two CSV files (clients and line items), groups the line items into invoices, and turns each invoice into a PDF. The tests don't use your real CSV files. They build small ones on the fly:

- `CLIENTS_CSV` is a one-client CSV (client `C001`, "Acme").
- `item_row(...)` builds one line-item CSV row. Every field has a sensible default, so a test only sets the field it wants to break. For example, `item_row(qty="abc")` gives a valid row except for a bad quantity.
- `build_from_text(lines)` writes the CSVs to a temporary folder, calls the real `build_invoices()` function on them, and returns `(invoices, errors)`. The folder is deleted afterwards, so the tests leave no files behind.

Each test then uses assertions to check that the right invoices were built and the right error messages came out.

**What it tests**

`MathTests` checks the calculations:

| Test | What it checks |
|---|---|
| `test_line_amount_rounds_half_up` | 3 × 0.335 = 1.005 must round to 1.01, the normal way people round money. Banker's rounding would give 1.00. |
| `test_subtotal_tax_and_total` | 100 + 50 gives a subtotal of 150.00, 10% tax is 15.00, and the total is 165.00. |
| `test_tax_percent_label_is_not_rounded` | A 7.5% rate is printed on the invoice as "Tax (7.5%)", not rounded to "8%". |

`ValidationTests` checks how bad data is handled:

| Test | What it checks |
|---|---|
| `test_valid_invoice_is_built` | Good rows produce one invoice with no errors: (2 × 10) + 5 = 25.00. |
| `test_bad_row_skips_whole_invoice_but_not_others` | If one row of INV-1 is bad, all of INV-1 is dropped (a partial invoice would show the wrong total), but INV-2 is still built. The error message names the line number. |
| `test_unknown_client_is_rejected` | A row pointing at client C999, which doesn't exist, is rejected. |
| `test_due_date_before_issue_date_is_rejected` | An invoice can't be due before it was issued. |
| `test_unsafe_invoice_id_is_rejected` | An ID like `../etc/passwd` is rejected. The invoice ID becomes the PDF's filename, so this stops a file being written outside the output folder. |
| `test_zero_quantity_and_negative_price_are_rejected` | A quantity of 0 and a price of -1 each produce an error. |
| `test_lines_with_different_dates_for_one_invoice_are_rejected` | All lines of one invoice must share the same client and dates. |
| `test_missing_column_raises_clear_error` | A CSV missing required columns stops the program with a clear "missing required column" error. |

## Project structure

```
invoice_generator.py        CLI, validation, totals, PDF rendering
benchmark.py                Synthetic data generator and timing
test_invoice_generator.py   Unit tests for math and validation
data/                       Small sample: 3 clients, 3 invoices (used in the examples above)
clients.csv                 Larger sample: 20 clients
line_items.csv              Larger sample: 40 invoices for those clients
line_items_with_errors.csv  Deliberately broken rows, to see error reporting
requirements.txt
CODE_GUIDE.md               Explanation of each file and function
```

## Limitations and next steps

- Tax is a single flat rate for the whole invoice. Per-item tax rates would need a `tax_rate` column.
- No logo or company address yet. Adding a logo is a good next feature.
- Invoices are not emailed. Sending them would need a separate step (for example Python's `smtplib`) that attaches each PDF to an email to the client's address.
