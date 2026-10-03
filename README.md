# Bank AI — Report Studio

## 1. Purpose

Report Studio makes bank data reports from requests in plain English.
Five agents process each request.
The application shows the result in a browser.
You can open the report and download its files.

This version uses a local ticket queue and fictional bank data.
It does not connect to a real bank or an external ITSM system.
Gemini receives the request and the database schema.
The extracted database rows stay on this computer.

The writing basis is [ASD-STE100, Issue 9](https://www.asd-ste100.org/).
The text uses short sentences, active voice, numbered procedures, and consistent technical terms.
The terms below identify software components and data.
A full independent STE dictionary review is not part of this release.

## 2. Technical terms

| Term | Meaning in this document |
| --- | --- |
| Agent | A software component that does one part of the report task. |
| API | An interface that lets one software component send data to another component. |
| API key | A secret value that gives the application access to Gemini. |
| Gemini | The Google model service that writes and examines SQL. |
| SQL | The language that selects data from database tables. |
| Schema | The table names, column names, types, and relations in a database. |
| Ticket | A saved request with an identifier, status, and process record. |
| Queue | The database that holds tickets. |
| Validation | The examination of SQL safety and request requirements. |
| Publication | The operation that saves all report files in their final directory. |
| Runtime directory | The directory that contains the databases and published reports. |
| CSV | A text file with table values separated by commas. |
| JSON | A file format that stores named values and lists. |
| HTML | The file format that the browser uses to show a report. |
| Metadata | The report record that contains the query, parameters, validation result, and file hashes. |
| File hash | A calculated value that helps identify changes in a file. |
| Fixture | A fixed request and SQL plan for an offline demonstration. |

## 3. System requirements

Use Python 3.11 or a later version.
Use a current web browser.
Use a Gemini API key for live requests.
The live request also needs an Internet connection.
The offline fixture does not need an API key.

The shell commands below apply to macOS and Linux.
On Windows, use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

## 4. Install the application

Do this procedure from the repository directory.

1. Make a Python virtual environment.

   ```bash
   python3 -m venv .venv
   ```

2. Activate the environment.

   ```bash
   source .venv/bin/activate
   ```

3. Install the application and the development tools.

   ```bash
   python -m pip install -e '.[dev]'
   ```

4. If `.env` does not exist, copy the example file.

   ```bash
   cp .env.example .env
   ```

5. Get an API key from your [Google AI Studio account](https://aistudio.google.com/apikey).
6. Open `.env` in a text editor.
7. Set `GEMINI_API_KEY` to your key.
8. Save the file.

The application does not show the key in the browser.
Git ignores `.env`.
The default model is `gemini-3.8-flash`.

## 5. Make the sample database

Do this procedure once for a new runtime directory.
Do not repeat it for a directory that already contains `bank.db`.
The command stops if the database already exists.

1. Activate the Python environment.
2. Run the initialization command.

   ```bash
   bank-agent init-demo
   ```

The command makes four fictional customers and ten transactions.
It also makes the local ticket queue.
The default directory is `runtime/`.

## 6. Start the browser interface

1. Run the server from the repository directory.

   ```bash
   bank-agent serve --port 8000
   ```

2. Open [Report Studio](http://127.0.0.1:8000) in your browser.
3. Keep the terminal open during the demonstration.

The server accepts connections from this computer only.
It does not make the application public.
The **Gemini configured** label shows that a key and the expected database schema are present.
The label does not prove that Google accepts the key.

If port 8000 is in use, select another port.

```bash
bank-agent serve --port 8001
```

Use the same port in the browser address.

## 7. Make a live report

1. Enter a request in **What would you like to know?**
2. Include the date range, currency, and required columns.
3. Select **Generate report**.
4. Follow the five steps in **Agent activity**.
5. Wait for the **Published** status.
6. Examine the data preview.
7. Select **Open report** to open the complete HTML report.
8. Select **CSV**, **JSON**, or **All files** to download the result.

**All files** gives you a ZIP file with all four report files.
**View SQL and validation** shows the SQL, parameter values, and validation explanation.
That section also gives you the metadata download.

The preview shows a maximum of 50 rows.
The downloaded files contain the full accepted result.
The interface shows the final publication directory below the preview.

The server processes one browser request at a time.
The interface prevents another submission while that request runs.
The browser request processes its own ticket.
It does not process an older ticket from the queue.

## 8. Example requests

Select an example button to put its text in the request field.
You can change the text before you submit it.

### Customer totals

The following text is a model input, not an operating instruction.

> Show each customer's ID, name, and total completed transaction amount in EGP for September 2026. Include only customers above 5000 EGP. Put the highest total first.

The sample data gives these results.

| Customer ID | Customer name | Total in EGP |
| --- | --- | --- |
| 2 | Demo Customer B | 14000.00 |
| 1 | Demo Customer A | 7500.00 |

### Transaction details

> List customer names and cities with their completed EGP debit transactions in September 2026. Include transaction ID, date, and amount in EGP. Order the rows by date.

### Customers without activity

> List the IDs and names of customers with no completed transactions in September 2026. Include all currencies. Order the rows by customer ID.

The third request needs a LEFT JOIN.
A customer with no matching transaction must remain in the result.

## 9. Open an earlier report

1. Go to **Recent requests**.
2. Select a completed request.
3. Examine the saved result.
4. Select the required download.

The list shows the latest 50 tickets.
The queue keeps older tickets on disk.
The browser remembers the selected ticket on this computer.
A page reload reads the saved status and report.
It does not submit the request again.

Select **New request** to clear the form and the preview.
This action does not delete a ticket or report.

## 10. Report publication

The report agent first writes the files in a temporary directory.
The agent then moves the complete directory to its final location.
The workflow marks the ticket completed after this move.

The default locations are as follows.

```text
runtime/
├── bank.db
├── tickets.db
├── reports/
│   └── <report-id>/
│       ├── report.html
│       ├── data.csv
│       ├── data.json
│       └── metadata.json
└── offline-demo/
    ├── bank.db
    ├── tickets.db
    └── reports/
```

The application calculates the report identifier from the ticket identifier.
Each ticket has its own report directory.
The application does not replace an existing report for that ticket.

| File | Contents |
| --- | --- |
| `report.html` | The request, result table, validation explanation, SQL, and download links. |
| `data.csv` | The column names and rows for spreadsheet applications. |
| `data.json` | The column names and unmodified result values. |
| `metadata.json` | The ticket, model, time, SQL, parameters, validation, process record, and file hashes. |

The server makes the ZIP download from these four published files.
The ZIP file does not contain the API key or databases.
The browser selects the download location.
Publication always uses the configured report directory.

To change the publication location, set `BANK_RUNTIME_DIR` and restart the server.
Initialize a new sample database if the new directory has no database.

## 11. Agent sequence and files

| Step | File | Operation |
| --- | --- | --- |
| 1. Fetch request | `Adhoc_agent/agents/request_agent.py` | Take ownership of the selected pending ticket. |
| 2. Write SQL | `Adhoc_agent/agents/sql_agent.py` | Send the request and schema to Gemini. Get one SQL plan with parameter values. |
| 3. Validate | `Adhoc_agent/agents/validation_agent.py` | Apply the local SQL rules. Ask Gemini if the query meets the request. |
| 4. Extract data | `Adhoc_agent/agents/extraction_agent.py` | Read the selected rows within the row and time limits. |
| 5. Publish report | `Adhoc_agent/agents/report_agent.py` | Save the report files in the final directory. |
| 6. Complete ticket | `Adhoc_agent/workflows/adhoc_workflow.py` | Save the final status and report location. |

The workflow controls the order of the agents.
It saves progress before each main operation.
The browser reads this progress and changes the activity display.
The report agent uses the extracted rows directly.
It does not ask Gemini to invent a report summary.

### Browser files

| File | Function |
| --- | --- |
| `Adhoc_agent/web/server.py` | Start the local HTTP server. Accept requests. Start the worker. Serve published files. |
| `Adhoc_agent/web/static/index.html` | Define the request form, activity list, report area, and history area. |
| `Adhoc_agent/web/static/style.css` | Set the colors, text, spacing, and layouts for wide and narrow screens. |
| `Adhoc_agent/web/static/app.js` | Submit requests. Read ticket progress. Show results. Set the download links. |

### Data and service files

| File | Function |
| --- | --- |
| `Adhoc_agent/Tools/queue.py` | Store tickets. Claim tickets without duplicate ownership. Save progress and final states. |
| `Adhoc_agent/Tools/gemini.py` | Send bounded requests to Google. Read the structured response. Keep provider details out of user errors. |
| `Adhoc_agent/Tools/schema.py` | Define the two tables, permitted columns, and business rules. |
| `Adhoc_agent/Tools/database.py` | Make the sample data. Open read-only connections. Examine the database schema. |
| `Adhoc_agent/Tools/sql_policy.py` | Examine SQL structure, columns, functions, joins, currencies, and parameters. Restrict SQLite access. |
| `Adhoc_agent/Tools/sql_excuter.py` | Run a read-only query. Apply the time limit and result size limit. |
| `Adhoc_agent/Tools/report_generator.py` | Write HTML, CSV, JSON, and metadata. Calculate file hashes. Publish the complete directory. |

The filename `sql_excuter.py` retains the spelling in the original repository.

### Application and test files

| File | Function |
| --- | --- |
| `Adhoc_agent/cli.py` | Read command options and start the selected operation. |
| `Adhoc_agent/__main__.py` | Start the CLI with `python -m Adhoc_agent`. |
| `Adhoc_agent/config.py` | Read environment settings and calculate runtime paths. |
| `Adhoc_agent/models.py` | Define the ticket, SQL plan, parameter, result, and error types. |
| `Adhoc_agent/demo.py` | Supply the fixed offline request and SQL plan. |
| `Adhoc_agent/**/__init__.py` | Identify the Python packages. |
| `tests/test_workflow.py` | Examine SQL controls, calculations, queue behavior, provider failures, and report files. |
| `tests/test_web.py` | Examine HTTP requests, progress, downloads, duplicate submissions, and access controls. |
| `pyproject.toml` | Define dependencies, package files, the command, and test settings. |
| `.env.example` | Give the local configuration template. |
| `.env` | Hold the local key and settings. This file is not in Git. |
| `.gitignore` | Exclude credentials, runtime data, caches, and build files from Git. |
| `.github/workflows/tests.yml` | Run the automated tests on Python 3.11, 3.12, and 3.13 in GitHub Actions. |
| `README.md` | Give the installation, operation, and file reference information. |

## 12. Database schema

The data database contains only `customer` and `transaction` tables.
The separate queue database contains the `tickets` table.

### Customer table

| Column | SQLite type | Meaning |
| --- | --- | --- |
| `customer_id` | INTEGER | Unique customer identifier. |
| `full_name` | TEXT | Fictional customer name. |
| `city` | TEXT | Customer city. |
| `segment` | TEXT | `retail` or `business`. |
| `created_at` | TEXT | ISO date when the customer record started. |

### Transaction table

| Column | SQLite type | Meaning |
| --- | --- | --- |
| `transaction_id` | INTEGER | Unique transaction identifier. |
| `customer_id` | INTEGER | Reference to `customer.customer_id`. |
| `amount_minor` | INTEGER | Nonnegative amount in minor currency units. |
| `currency` | TEXT | `EGP` or `USD`. |
| `transaction_type` | TEXT | `credit` or `debit`. |
| `status` | TEXT | `completed`, `pending`, or `failed`. |
| `transaction_date` | TEXT | ISO transaction date. |

Use `customer.customer_id = transaction.customer_id` for the join.
SQL must quote the table name `"transaction"`.
The name is also a SQL keyword.

Divide `amount_minor` by `100.0` to get the amount in EGP or USD.
Do not add EGP and USD amounts together.
The schema contains no exchange rates or account balances.
Credits and debits are separate categories.
The amount does not have a direction sign.

Dates use `YYYY-MM-DD` with UTC date definitions.
Monthly filters include the first day and exclude the first day of the next month.
Transaction totals include completed transactions unless the request gives a different status.

## 13. SQL controls

The local rules permit one SELECT statement.
The statement can use one table or both tables.
An INNER JOIN or LEFT JOIN must require the customer relation.
The query must identify its output columns.
Only `COUNT(*)` can use a wildcard.

The rules do not permit database writes or schema reads.
They do not permit cross joins, subqueries, CTEs, unions, or window functions.
They limit functions to the list in `sql_policy.py`.
SUM and AVG operations on money must separate currencies or select one currency.

Gemini supplies named parameters for filter values.
SQLite binds these values separately from the SQL text.
The application also uses read-only mode and a SQLite authorizer.
The authorizer limits access to the specified tables, columns, and functions.

The local examination proves that the SQL meets these technical restrictions.
The Gemini review compares the SQL with the request.
Neither operation is business approval for a real bank report.

## 14. Configuration

The application reads `.env` from the current directory.
Existing environment variables take precedence over `.env` values.
Restart the server after a configuration change.

| Setting | Default | Function |
| --- | --- | --- |
| `GEMINI_API_KEY` | Empty | Key for the Gemini API. |
| `GOOGLE_API_KEY` | Empty | Alternative key if `GEMINI_API_KEY` is empty. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model for SQL generation and semantic review. |
| `BANK_RUNTIME_DIR` | `runtime` | Root directory for local data and reports. |
| `BANK_MAX_ROWS` | `10000` | Maximum number of result rows. The permitted range is 1 to 100000. |
| `BANK_QUERY_TIMEOUT_SECONDS` | `5` | Query time limit. The value must be above zero and at most 60. |

Each ticket uses a maximum of two Gemini generation calls.
An early failure can stop the process before the second call.
Each call has one attempt and a 30-second timeout.
The application does not make automatic provider retries.

Use `--runtime` before the subcommand to select a different runtime directory.

```bash
bank-agent --runtime /absolute/path/to/demo serve --port 8000
```

## 15. Ticket states and faults

| Status | Meaning | Operator action |
| --- | --- | --- |
| `pending` | The queue holds the ticket. | Wait for the browser worker or run the CLI worker. |
| `in_progress` | A worker owns the ticket. | Read the agent activity. |
| `completed` | The report files exist in the final directory. | Open or download the report. |
| `needs_clarification` | The request or query does not give a clear result. | Read the reason. Change the request. Submit a new ticket. |
| `failed` | A technical operation stopped. | Read the error. Correct the cause before another submission. |

An empty result is not a failure.
The report contains its column names and a no-records message.
If the result exceeds the row limit, the workflow stops.
It does not publish a partial result.

| Problem | Corrective action |
| --- | --- |
| Setup needed | Set the key or initialize the sample database. Restart the server after a configuration change. |
| Google rejects the key | Replace the local key with a valid Gemini key. Restart the server. |
| Model unavailable | Set an available model in `.env`. Restart the server. |
| Provider request fails | Examine Internet access, model access, and Google quota. |
| Result exceeds the row limit | Add a narrower date range or more filters to the request. |
| Query exceeds the time limit | Reduce the request scope. |
| Publication fails | Make sure that the runtime directory permits writes and has sufficient free space. |
| Connection unavailable | Start the server. Reload the browser page. |
| Port unavailable | Start the server on another port. |

A forced process stop can leave a ticket `in_progress`.
The application does not automatically take ownership of that ticket again.
After a server restart, submit a new request if the earlier worker has stopped.
Do not infer publication from a partial process record.
Use the completed status and saved report files.

## 16. CLI operation

You can use the agents without the browser.

```bash
bank-agent submit "Show completed EGP transaction totals by customer for September 2026."
bank-agent run --max-tickets 1
bank-agent tickets
```

The CLI worker selects the oldest pending ticket.
The browser worker selects the ticket from its own submission.
A database transaction prevents both workers from owning the same ticket.

After you correct a technical fault, you can retry a failed ticket.

```bash
bank-agent retry TICKET_ID
bank-agent run --max-tickets 1
```

Only failed tickets and clarification tickets permit this retry operation.
Submit a new ticket if you need to change the request text.
`--max-tickets` permits values from 1 to 100.
There is no scheduled worker or automatic background API use.

`python -m Adhoc_agent` is an alternative to `bank-agent` for every subcommand.

## 17. Offline demonstration

1. Run the fixed fixture.

   ```bash
   bank-agent demo
   ```

2. Open the report path from the command output.

This command uses a separate database under `runtime/offline-demo/`.
It makes no Gemini calls.
It does not consume live pending tickets.
The report identifies the offline fixture.
The fixture cannot translate a new request.

## 18. Stop the server

1. Return to the terminal that runs Report Studio.
2. Press Ctrl-C.
3. Wait for the process to exit.

A running browser report finishes before normal server exit.
Saved reports remain on disk.
The browser cannot submit requests after the server stops.

## 19. Tests and packaging

1. Install the development dependencies as given in section 4.
2. Run the automated tests.

   ```bash
   pytest -q
   ```

3. Run the code examination tools.

   ```bash
   ruff check .
   ruff format --check .
   ```

The tests use fictional data and model stubs.
They do not use API credits.
The web tests need permission to open temporary localhost ports.

The tests cover joins, money filters, dates, empty results, unsafe SQL, and parameter values.
They also cover time limits, row limits, publication failures, concurrent claims, progress, and downloads.
A live browser demonstration is a separate verification step.

`pyproject.toml` includes the browser assets in the Python package.
The server does not need Node.js or a separate frontend build.

## 20. External integration boundary

The local version does not send email or close external ITSM tickets.
The completed status applies to the local queue only.
Real integration needs the following project information.

- The approved ITSM interface and ticket states.
- The real database schema and SQL dialect.
- Restricted read-only database access.
- The report destination and publication permissions.
- The rules for business approval and external ticket completion.

Keep database rows local unless the bank approves a different data path.
Use `queue.py`, `database.py`, and `report_generator.py` as the corresponding integration boundaries.

## 21. Local HTTP interface

The browser uses these routes in `web/server.py`.
The routes do not expose the API key.

| Method and route | Function |
| --- | --- |
| `GET /` | Return the Report Studio page. |
| `GET /static/app.js` | Return the browser code. |
| `GET /static/style.css` | Return the page styles. |
| `GET /api/status` | Return local readiness, model name, report directory, and active ticket. |
| `GET /api/tickets` | Return the latest 50 tickets. |
| `GET /api/tickets/<ticket-id>` | Return one ticket and its current progress. |
| `POST /api/tickets` | Save a request and start its worker. |
| `GET /reports/<ticket-id>/<filename>` | Open a file from a completed report. |
| `GET /download/<ticket-id>/<filename>` | Download a file from a completed report. |
| `GET /download/<ticket-id>/bundle.zip` | Download all four report files. |

The POST request uses JSON with a `request` string.
The string must contain 1 to 8000 characters.
The browser sends a server token with the POST request.
The server does not accept POST requests from another website.
Only the four specified report filenames and the ZIP download are available.
