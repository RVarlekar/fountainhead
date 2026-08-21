# Bill OCR — how it works

**This page is read-only.** It ships with the software itself and can only change
through a code deployment — never edited on screen. What you read here is what the
system actually does, in the order it does it.

*Last updated with the 21 August 2026 release.*

---

## 1. What happens when a bill is read

1. The scanned bill (photo or PDF) is sent to an AI reader with one instruction:
   **copy what is printed — never calculate, round, or invent values.**
2. The reader returns the supplier, invoice number and date, every line item
   (quantity, rate, amount), the tax block (taxable value, CGST/SGST/IGST,
   round-off, grand total), any extra charges, per-page subtotals on multi-page
   documents, and the approval marks (signatures and stamps) it can see.
3. **Arithmetic is never trusted to the AI.** A deterministic layer then checks
   everything by calculation:
   - each line's quantity × rate must match its printed amount (within ₹1);
     where they disagree, the printed amount wins and the rate is corrected,
     with a note saying so;
   - the lines must add up to the taxable value;
   - taxable + taxes + round-off must equal the printed grand total;
   - a round-off is only ever derived when the residual is within ₹1 — a larger
     gap is a real discrepancy and is **flagged, never absorbed**.
4. The result is shown to a person. **Nothing is saved, posted or submitted
   automatically — ever.** The person reviews and presses Save; all the normal
   approvals then apply unchanged.

## 2. The tally verdict

Every reading ends with one question: *will the document total exactly what the
bill prints?* A green banner means yes, with the arithmetic shown. A red banner
means no — with the gap, and on multi-page scans a per-page breakdown ("page 1:
5 lines totalling ₹6,300…") so a missing page is obvious. The same check runs
again when the document is saved: a mismatched total produces a warning (orange,
never blocking — the human decides).

## 3. GST treatment — decided 19–20 August 2026

Whether GST becomes separate tax rows is a property of the **Company**, via the
flag *"GST registered (Bill OCR books tax rows)"*:

- **Flag OFF (the school — no GST registration, no input credit):** item rows
  keep the **exact printed rates**. The bill's GST plus its printed round-off is
  booked as **one charge row (category "Total") into the same expense head the
  supplier's own past invoices book to** — so the P&L carries the full cost in
  one head, exactly like the manual entry always has. **No GST ledger is touched
  and none is created.** If no head can be inferred from history, the system
  warns and books nothing rather than guessing.
- **Flag ON (GST-registered entities, e.g. Protego):** the printed CGST/SGST/
  IGST amounts fill the Purchase Taxes and Charges table as separate rows,
  exactly as printed.
- Bills whose line amounts already include the tax get no extra row in either
  mode — adding one would double-count.

Confirmed by accounts (Krunal Bhagat, 21 Aug): pre-GST rates on the lines with
GST as a combined charge line is the intended booking.

## 4. Dates

- The invoice date is read off the bill and **offered**, never forced — Indian
  DD/MM is assumed, and a genuinely ambiguous date is flagged for confirmation.
- A bill dated **before the current + previous month window** gets a prominent
  warning (late bills need someone's attention, and they affect TDS timing).
  The window is configurable per site. A **future** date is flagged as a likely
  misread. No emails are sent — warnings show on screen and the queue stays
  visible for the manager's dashboard.

## 5. Duplicates

Three separate checks, all warnings a human can overrule:

1. **Same supplier + same invoice number** already on a Receipt or Invoice.
2. **Same supplier + same date + a different invoice number** — two bills from
   one vendor in one day can be the same purchase billed twice.
3. **The same file (byte-for-byte)** queued again — caught by content hash.

## 6. Approval marks

The physical signature on the bill **is** the approval in this process. The
reader reports the signatures and stamps it sees; an upload with **no school-side
mark at all** gets a warning ("bills are signed before entry — check before
saving"). This is advisory: the mark may be on another page, and the human
decides.

## 7. Item and supplier matching

- Suggestions are scored on word overlap between the bill's wording and the
  item master, blended with **this supplier's own history** ("their usual").
- Gujarati/Hindi text is **translated to meaning** (not transliterated) and both
  readings are matched.
- **Nothing is auto-picked**, with one deliberate exception: when a person has
  previously chosen an item for *exactly this wording*, that choice is replayed
  and labelled "you taught this". The memory only ever learns from human clicks.
- Creating a new item is deliberately slow: near-matches must be shown and
  acknowledged first, and every created item is flagged for the weekly review.
- The **Item Group is never filled in automatically** — it decides who approves
  the document, so it is offered as labelled buttons only.

## 8. Charges, challans, multi-page

- A charge on top of the items (supervision %, freight) becomes its own labelled
  row — dropping it is how a ₹13,500 bill once became a ₹11,250 receipt.
- A **challan** can be attached alongside a lump-sum bill: line detail is read
  from the challan, every amount still comes from the bill.
- Multi-page bills report per-page line subtotals and any printed "page X of Y",
  so a missing page in the scan is caught at once.

## 9. Cost and caching

- Reading a bill costs roughly **₹2–3** (it replaces 3–5 minutes of typing).
- Every reading is **cached against the file's content**: re-attaching, reloading,
  or re-uploading the same bill — even under a different file name — reuses the
  stored reading free. A bill is never paid for twice in the normal flow.
- "Read again, carefully" deliberately bypasses the cache for a slower,
  re-verified pass; the correction box re-reads with the user's own words as
  reviewer instructions. Both cost one fresh reading.

## 10. What this system will never do

- Post, submit, or save any purchase document by itself.
- Choose the Item Group, or silently create items or suppliers.
- Absorb an arithmetic gap the bill's own printed figures don't explain.
- Send emails or notifications — everything surfaces on screen and dashboards.
- Touch a GST ledger for an entity without GST registration.

## 11. Pending accounting rules (not yet active)

These are documented so the roadmap is auditable; none of them run today:

- **TDS suggestions** — awaiting the confirmed section/rate/threshold table for
  FY 2026-27 (194J/194I/194C/194H/194Q), the 20% no-PAN rule, and
  accrual-vs-payment timing from accounts. TDS will be suggested from the
  vendor master once confirmed — never auto-deducted.
- **ITC / RCM handling** — relevant only to GST-registered entities; planned for
  the Protego rollout.
