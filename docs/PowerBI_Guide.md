# Power BI Guide

The finished report is `powerbi/Pharma_MES.pbix`. It reads CSV exports of the views below, written by `python Pharmaceutical_MES/export_powerbi.py`.
This guide explains the model, and how to switch to a live PostgreSQL connection.

## Live connection (optional)

Instead of the CSVs, use **Get Data → PostgreSQL database**: server `localhost`, database `mes_portfolio`, mode **Import**.
Select these views:

| View | Use |
|---|---|
| `v_batch_progress` | batch status, percent complete, open deviations |
| `v_review_by_exception` | exceptions per batch for QA |
| `v_genealogy` | lot-to-batch traceability |

Relationships: `v_batch_progress[batch_no]` 1 → * `v_review_by_exception[batch_no]` and `v_genealogy[batch_no]`.

## Measures (DAX)

```DAX
Batches = DISTINCTCOUNT ( v_batch_progress[batch_no] )

Released = CALCULATE ( [Batches], v_batch_progress[status] = "RELEASED" )

Awaiting QA = CALCULATE ( [Batches], v_batch_progress[status] = "COMPLETED" )

Open Deviations = SUM ( v_batch_progress[open_deviations] )

Right First Time % =
DIVIDE (
    CALCULATE ( [Batches], v_batch_progress[total_deviations] = 0,
                v_batch_progress[status] IN { "COMPLETED", "RELEASED" } ),
    CALCULATE ( [Batches], v_batch_progress[status] IN { "COMPLETED", "RELEASED" } )
)

Avg Release Time (h) =
AVERAGEX (
    FILTER ( v_batch_progress, v_batch_progress[status] = "RELEASED" ),
    DATEDIFF ( v_batch_progress[completed_at], v_batch_progress[disposition_at], HOUR )
)
```

## Layout

1. **Batch status**: cards (Batches, Released, Awaiting QA, Open Deviations, Right First Time %), a bar chart of batches by status, and a table from `v_batch_progress` with conditional formatting on `open_deviations`.
2. **Review by exception**: matrix with batch_no as rows and exception_type as columns, showing the count, and a details table. Use a slicer on batch_status.
3. **Traceability**: slicers for lot_no and batch_no, and a table from `v_genealogy`. Optionally add a decomposition tree going lot → batch → product.

Save screenshots as `docs/img/powerbi_*.png` and link them in the README.
