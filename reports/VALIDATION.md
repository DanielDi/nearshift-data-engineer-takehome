# Validation and reconciliation

Original CSV files remain unchanged. Source columns are loaded as strings (blank cells become SQL NULL); typed analytics tables are checked against them.

## Raw row counts

| Table | Rows |
|---|---:|
| orders | 99,441 |
| order_items | 112,650 |
| order_payments | 103,886 |
| order_reviews | 99,224 |
| customers | 99,441 |
| products | 32,951 |
| category_translation | 71 |

## Automated checks

| Check | Result | Observed difference/count |
|---|---|---:|
| order row count | PASS | 0 |
| item row count | PASS | 0 |
| payment row count | PASS | 0 |
| product row count | PASS | 0 |
| customer identity count | PASS | 0 |
| mart order row count | PASS | 0 |
| duplicate order IDs | PASS | 0 |
| null order IDs | PASS | 0 |
| duplicate item keys | PASS | 0 |
| duplicate payment keys | PASS | 0 |
| items without orders | PASS | 0 |
| payments without orders | PASS | 0 |
| orders without customers | PASS | 0 |
| items without products | PASS | 0 |
| invalid item prices | PASS | 0 |
| invalid payment values | PASS | 0 |
| invalid purchase timestamps | PASS | 0 |
| raw item price difference (cents) | PASS | 0 |
| raw freight difference (cents) | PASS | 0 |
| raw payment difference (cents) | PASS | 0 |
| order item subtotal differences | PASS | 0 |
| order payment total differences | PASS | 0 |
| raw delivered merchandise difference (cents) | PASS | 0 |
| category total difference (cents) | PASS | 0 |
| monthly total difference (cents) | PASS | 0 |

## Payment versus item and freight totals

Payment and merchandise value are different measures. Payments can occur on canceled or unavailable orders. Do not force their totals to match.

| Status | Orders | Item value | Freight | Payments | No items | No payment | Mismatch orders |
|---|---:|---:|---:|---:|---:|---:|---:|
| delivered | 96,478 | R$ 13,221,498.11 | R$ 2,198,275.64 | R$ 15,422,461.77 | 0 | 1 | 299 |
| shipped | 1,107 | R$ 150,727.44 | R$ 26,401.90 | R$ 177,213.96 | 1 | 0 | 2 |
| canceled | 625 | R$ 95,235.27 | R$ 10,650.45 | R$ 143,255.60 | 164 | 0 | 2 |
| unavailable | 609 | R$ 2,007.69 | R$ 132.80 | R$ 126,479.51 | 603 | 0 | 0 |
| invoiced | 314 | R$ 61,526.37 | R$ 7,462.38 | R$ 69,137.99 | 2 | 0 | 0 |
| processing | 301 | R$ 60,439.22 | R$ 8,954.89 | R$ 69,394.11 | 0 | 0 | 0 |
| created | 5 | R$ 0.00 | R$ 0.00 | R$ 688.10 | 5 | 0 | 0 |
| approved | 2 | R$ 209.60 | R$ 31.48 | R$ 241.08 | 0 | 0 | 0 |

There are **303** orders with both items and payments whose totals differ by more than R$0.01; see `payment_exceptions.csv` for the order-level reconciliation.
Missingness retained in the model: **610** products have no category, **13** categorized products have no English translation, and **8** delivered orders have no actual delivery date.
The dataset does not provide a reliable refund ledger, so payment discrepancies are exposed rather than imputed.
Source timestamps have no documented time-zone offset; they are treated as local, naive timestamps without conversion.
