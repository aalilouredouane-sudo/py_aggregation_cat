# py_aggregation_cat

Python translation of the R aggregation script for Man-Made catfiles.

For each entity, the code aggregates the catfiles by risk, segment and run, together with the `pool_property` files. It then computes the following metrics:

- **mean**: average annual loss (AAL);
- **AEP200**: 200-year return period annual loss;
- **STEC**: AEP200 − mean;
- **OEP200**: 200-year return period largest annual event.

An optional **Group view** sums the strips of all entities after converting them to euros.

The results match the R script exactly, including file processing order, number formatting and `Checkpool` messages.

---

## Folder structure

```
py_aggregation_cat/
├── main.py                  # entry point: run parameters and pipeline launch
├── requirements.txt         # dependencies (numpy, pandas, openpyxl)
├── README.md
└── aggregation_cat/         # computation package
    ├── __init__.py          # classes exposed by the package
    ├── config.py            # constants (number of years, return period, labels, R precision)
    ├── pipeline.py          # orchestration: entity discovery, computation, export, Group view
    ├── entity.py            # aggregation of one entity (risks, segments, runs, pool files)
    ├── group.py             # Group aggregation (sum of entities converted to euros)
    ├── reader.py            # reading catfiles / pool files and building annual strips
    ├── metrics.py           # mean / AEP200 / STEC / OEP200 computation
    ├── exporter.py          # Excel and CSV output
    └── rcompat.py           # exact reproduction of R behaviours (sums, sorting, formatting, all.equal, fwrite)
```

### Expected input layout

```
<folder>/
├── FRA/                              # entity folder (name = key of `units`)
│   ├── CF/                           # risk WITHOUT segments: catfiles directly in the folder
│   │   ├── FRA_CF.csv
│   │   └── FRA_CF_pool_property.csv  # optional: replaces the sum of the catfiles
│   └── TE/                           # risk WITH segments
│       ├── RL/                       # segment
│       │   └── run1/                 # run: exactly 1 catfile (+ optional pool files)
│       │       ├── FRA_TE_RL.csv
│       │       └── FRA_TE_RL_pool_property.csv
│       └── RM/
│           └── run1/
│               └── FRA_TE_RM.csv
└── XL/
    └── ...
```

- An entity folder can be at any depth under `folder`. It must be named after a key of `units` and contain at least one subfolder.
- **Catfile** (`.csv`): columns `year` (or `*yearid*`), `eventid`, then one column per LoB. Column names are case-insensitive. The separator is detected automatically, and decimal commas are accepted.
- **Pool file**: any file whose path contains `pool_property`. Columns `year`, `eventid`, `loss`.
- Years must be between 1 and `N_YEARS` (50,000).

---

## User guide

1. **Install the dependencies.** Run `pip install -r requirements.txt`. `main.py` also installs any missing packages automatically at startup.
2. **Set the parameters** in [main.py](main.py):

   | Parameter | Purpose |
   |---|---|
   | `folder` | Root folder of the catfiles. |
   | `output_dir` | Output folder. If omitted, files are written to `folder`, as the R script does. |
   | `units` | Catfile unit per entity: 1 if amounts are in units, 1000 if they are in thousands, etc. The keys of this dictionary define which entities are looked for. |
   | `is_xl_pool_format` | `True` if all XL perils are already in pool format. The XL entity is then excluded from the computation. |
   | `group` | `True` to also produce the Group view. |
   | `fx_rates` | Exchange rates to euro per entity. Required for every processed entity when `group=True`. |
   | `by_lob` | `True` to also produce the summaries per LoB (see below). Existing outputs are unchanged. |

3. **Run the computation**: `python main.py`.
4. **Collect the outputs** in `output_dir`:

   | File | Content |
   |---|---|
   | `Gross_MM_reconciliation_<entity>.xlsx` | Sheet `Gross_STEC`: mean, AEP200 and STEC per risk and in total. Sheet `Local_AAL_strips`: annual losses (50,000 years) per risk and in total. |
   | `<entity>_summary.csv` | One row per risk, plus `Total`, plus one row per run of segmented risks: mean, AEP200, STEC, OEP200, `Checkpool`. |
   | `All_entities_summary.csv` | Concatenation of the `<entity>_summary.csv` files. |
   | `summary_all_subrisks.csv` | Metrics for each catfile, each segment and each segment merge (`All`). |
   | `Gross_MM_reconciliation_Group.xlsx` | Only if `group=True`. Same format as the entity files, with the strips of all entities in euros. |
   | `<entity>_summary_by_lob.csv` | Only if `by_lob=True`. Columns `Entity`, `risk`, `LoB`, mean, AEP200, STEC, OEP200: one row per (risk, LoB) and the risk `Total`, then a `Total` block (all risks) per LoB and in total. |
   | `All_entities_summary_by_lob.csv` | Only if `by_lob=True`. Concatenation of the `<entity>_summary_by_lob.csv` files. |

   **Per-LoB summaries** are built from the catfiles only, because pool files have no LoB detail. For segmented risks, the same LoB is summed across segments for each event, and the runs are added together. The `Total` LoB uses the event total, so its OEP200 is the largest event across LoBs. As a result, the risk `Total` of the per-LoB file equals the main summary only for risks whose reported figures come from the catfiles (no pool file, or a pool file equal to the catfiles).

   The **`Checkpool`** column compares the pool file with the catfiles using R's `all.equal`. It is `TRUE` when they are equal. Otherwise it holds the first difference (`Column 'loss': Mean relative difference: …`), or `NO POOL FILE` / `No pool` when there is no pool file.

5. **Precision of the last digits.** `R_LONG_DOUBLE` in [config.py](aggregation_cat/config.py) must match the machine running the reference R script:
   - `True` for R on Windows or Intel Mac;
   - `False` for R on Apple Silicon Mac.

   Only the last significant digits and the `Checkpool` messages depend on it.

---

## Code description

### `main.py`
Entry point. It checks that `numpy`, `pandas` and `openpyxl` are installed and installs any that are missing. It then builds an `AggregationCatPipeline` with the run parameters and calls `.run()`.

### `aggregation_cat/config.py`
Global constants:
- `N_YEARS = 50000` and `RETURN_PERIOD = 200`. From these, `RANK = 250` is the rank of the loss used for the 200-year AEP and OEP.
- `POOL_TAG` (`pool_property`), `CATFILE_PATTERN`, and the columns that are not LoBs (`year`, `eventid`, `model_id`…).
- Labels: `Total`, `Group`, `All`, `XL`, `NO POOL FILE`, `No pool`, `AEP200`, `OEP200`.
- `R_LONG_DOUBLE`: the precision of R's sums to reproduce (see the user guide).

### `aggregation_cat/pipeline.py` — `AggregationCatPipeline`
Orchestrates the full run:
- `entity_folders()` recursively searches `folder` for folders named after an entity of `units` that contain at least one subfolder. If an entity appears several times, only the first occurrence is kept.
- `run()`:
  1. for each entity (except XL when `is_xl_pool_format`), runs `EntityAggregation.build()` and writes `Gross_MM_reconciliation_<entity>.xlsx` and `<entity>_summary.csv`;
  2. if `group=True`, adds the entity's strips, multiplied by its exchange rate, to the `GroupAggregation`, then writes `Gross_MM_reconciliation_Group.xlsx`;
  3. writes `summary_all_subrisks.csv` and `All_entities_summary.csv`.
- `_group_aggregation()` checks that every entity has an exchange rate. The Group view columns list the risks of all entities, in order of first appearance.

### `aggregation_cat/entity.py` — `EntityAggregation`
Computes everything for one entity. Each subfolder of the entity is a risk, handled in one of two ways.

- **Risk without segments** (`_flat_risk`):
  - each catfile in the folder is turned into an annual strip, and the strips are summed;
  - if there are pool files, their strip **replaces** the sum of the catfiles for reporting, and `Checkpool` receives the result of `all_equal(pool, sum of catfiles)`.
- **Risk with segments** (`_segmented_risk`): for each run of the first segment:
  - the single catfile of each segment for that run is read;
  - the segments are merged event by event (`combine_segments`);
  - if the run has pool files, each of them is added to the risk, with its own result row and `Checkpool`. For XL, pool files are taken from all segments; for other entities, only from the first one;
  - otherwise, the merged segments are added to the risk (`Checkpool = No pool`).
- `build()` assembles the entity result:
  - the summary table: one row per risk, one `Total` row, then the run rows;
  - the strips per risk and in total;
  - the figures of the `Gross_STEC` sheet;
  - the rows of `summary_all_subrisks.csv`.

  The Total `max_loss` is the maximum across risks, so the Total OEP is the largest event across all risks.

### `aggregation_cat/reader.py`
Reads the files and builds annual strips. A strip is a `year`, `loss`, `max_loss` table over 50,000 years.
- `read_csv` detects the separator, reads the file without loss of precision and lowercases column names.
- `read_catfile` renames `*yearid*` to `year`, converts decimal commas, computes `total` (the sum of the LoBs) and drops `model_id`.
- `single_catfile` returns the single catfile of a run folder and raises an error if there is not exactly one.
- `combine_segments` merges segments on (`year`, `eventid`) with a full outer join: an event missing from a segment counts as 0 in that segment. `total` is then recomputed.
- `yearly_strip` computes, for each year, `loss` (sum of events) and `max_loss` (largest event), then multiplies by the unit. A year without events is 0.
- `pool_yearly_strip` aggregates pool files: first summed per event, then per year. `loss` is accumulated across files and `max_loss` is the maximum across files.
- `zero_strip` creates an all-zero strip. `add_strip` adds two strips: sum of `loss`, maximum of `max_loss`.
- A year outside 1..`N_YEARS` raises an explicit error.

### `aggregation_cat/metrics.py`
- `xth_largest` returns the 250th largest value, the equivalent of `sort(x, decreasing = T)[250]` in R. NAs are ignored.
- `strip_stats` returns `mean`, `AEP200` (250th largest annual loss), `STEC` (AEP200 − mean) and, if `max_event` is given, `OEP200` (250th largest annual event).

### `aggregation_cat/group.py` — `GroupAggregation`
- `add` adds an entity's strips, multiplied by its exchange rate, to each risk column and to the Total. A risk missing from the entity counts as 0.
- `build` returns the Group's `Gross_STEC` sheet (mean, AEP200 and STEC per column) and `Local_AAL_strips` sheet.

### `aggregation_cat/exporter.py`
- `ExcelExporter` writes a workbook with the `Gross_STEC` and `Local_AAL_strips` sheets. NAs become empty cells.
- `CsvExporter` writes a CSV in R's `fwrite` format (see `rcompat.fwrite`).

### `aggregation_cat/rcompat.py`
Reproduces exactly the R behaviours the results depend on:
- **Sums and means** (`row_sums`, `group_sums`, `r_sum`, `r_mean`):
  - if `R_LONG_DOUBLE = True`, compensated or exact accumulation, mimicking R's 80-bit long double;
  - otherwise, sequential summation in 64-bit double.
- **Sorting and listing** (`sort_key`, `list_dirs`, `list_files`, `has_tag`): R's alphabetical order (ICU collation). Case is ignored at the first level, punctuation sorts before digits and letters, and a lowercase letter sorts before the matching uppercase one. This order sets the order in which files are processed.
- **Number formatting** (`format_number`): equivalent of `as.character` (15 significant digits) and `format` (7 digits). The code chooses between fixed and scientific notation the way R does.
- **`all_equal`**: equivalent of R's `all.equal` applied to two data.tables. Returns `TRUE` or the message of the first difference (`Mean relative difference: …`). This is the value of the `Checkpool` column.
- **`fwrite`**: comma-separated CSV, numbers with 15 significant digits, NAs written as empty fields, quotes only when needed.
