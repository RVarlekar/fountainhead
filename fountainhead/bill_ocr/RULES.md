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

## 3. GST treatment — ruled 31 August 2026

Whether GST becomes separate tax rows is a property of the **Company**, via the
flag *"GST registered (Bill OCR books tax rows)"*:

- **Flag OFF (the school — no GST registration, no input credit):** the bill's
  GST plus its printed round-off is **folded into the item rates in proportion
  to each line**, so the document shows **GST-inclusive rates and no separate
  GST anywhere** — the same way accounts has always entered bills by hand.
  The last line absorbs the rounding remainder so the document lands on the
  bill's exact printed total. **No GST ledger is touched and none is created.**
  Ruled in writing by Chetan Shah (31 Aug): *"rate with GST including. No
  separate GST will be shown in invoice."* (This supersedes the earlier
  one-charge-row shape verified on 21 Aug.)
- **Flag ON (GST-registered entities, e.g. Protego):** the printed CGST/SGST/
  IGST amounts fill the Purchase Taxes and Charges table as separate rows,
  exactly as printed — **unless the "Claim GST credit" box on the bill is left
  unticked**, in which case the GST folds into the rates for that bill (credit
  is item/usage-based, not vendor-based — 1 Sept rules).
- Bills whose line amounts already include the tax are never touched — adding
  or folding again would double-count.
- Only the PRINTED GST + round-off is ever distributed. An unexplained gap
  between the lines and the printed total stays visible and fails the tally.

### 3a. GST credit and RCM (GST-registered entities only)

Two checkboxes on the bill, **mutually exclusive** (per accounts' written rules,
1 Sept — what carries RCM never also gives credit):

- **Claim GST credit (ITC)** — tick only when this bill's GST is claimable.
  Eligibility is maintained **category-wise** in the accounts-editable *ITC
  Eligibility Category* master (professional/legal/IT/office/repairs/security/
  housekeeping = generally eligible; personal, canteen/food, passenger
  transport, motor vehicles = blocked/restricted), never in code. Unticked:
  the GST stays in the cost.
- **RCM applicable** (e.g. lawyer bills): the bill is booked without its GST
  here; the RCM liability is created by the standard adjustment entry
  (Dr Input GST / Cr RCM-Output GST on the invoice value), **accumulates in GST
  Payable, and is settled in one consolidated monthly voucher** — confirmed by
  accounts, 1–2 Sept.

## 4. Dates

- The invoice date is read off the bill and **offered**, never forced — Indian
  DD/MM is assumed, and a genuinely ambiguous date is flagged for confirmation.
- A bill dated **before the current + previous month window** gets a prominent
  warning (late bills need someone's attention, and they affect TDS timing).
  The window is configurable per site. A **future** date is flagged as a likely
  misread. No emails are sent — warnings show on screen and the queue stays
  visible for the manager's dashboard.

## 5. Duplicates

Four separate checks, all warnings a human can overrule:

1. **Same supplier + same invoice number** already on a Receipt or Invoice.
2. **Same supplier + same date + a different invoice number** — two bills from
   one vendor in one day can be the same purchase billed twice.
3. **The same file (byte-for-byte)** queued again — caught by content hash.
4. **The Journal Voucher route (imprest bills):** a JV whose supplier + reference
   number matches a bill number — in either direction. Entering a bill that a JV
   already booked warns; saving a JV whose reference an invoice (or another JV)
   already carries warns too. Whichever way the second entry comes, the person
   is told at entry time (accounts' explicit 26 Aug ask). Invoice numbers alone
   are never trusted — handwritten bills often carry a dummy ("cash", a date).

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

## 10. TDS — computed at booking, suggested, never silently deducted

Built to accounts' written spec (26 Aug mail) and clarifications (1–2 Sept):

- Rules live in the **Bill TDS Rule** master — rates, thresholds, treatments are
  **data accounts can edit**, never code. Rules carry effective dates; a
  computation always uses the rule in force **on the bill date**, so next year's
  change can never rewrite a booked entry (no retroactivity).
- TDS is determined from the **nature of the payment + vendor type + section +
  threshold — never from a ledger name**. A vendor with a TDS section is NOT
  deducted automatically: below the threshold, no TDS.
- The **vendor-wise cumulative** (GST-exclusive, per financial year) is tracked
  from the supplier's own submitted invoices; once the aggregate threshold is
  crossed, every later bill that year is subject. The crossing bill follows the
  rule's own treatment (full amount, or only the excess — configurable per
  section, e.g. 194Q taxes only the excess over ₹50 lakh).
- TDS is computed on the **GST-exclusive** base. A **missing or invalid PAN**
  triggers the higher rate (20% default) and flags the bill.
- Posting: **one liability ledger per section** — "TDS Payable – 194J",
  "TDS Payable – 194C", "TDS Payable – 192B" and so on; **calculated and
  deducted at bill booking, same day** (accounts, 2 Sept).
- On screen, the FULL working is always shown — section, rate, previous
  cumulative, this bill, cumulative, threshold, TDS amount, net payable, and the
  reason in words — and the deduction row is added only when the maker clicks
  **Apply**. The suggestion changes nothing by itself.

## 11. Narration

Every filled document carries a prefilled narration in accounts' own convention
(their samples, 1 Sept): *party name – Bill No. X: what was bought/done. Details
as per the attached bill.* Always editable — the narration is the accountant's;
the system only saves the typing.

## 12. Quick post (single-line bills)

66.8% of receipts have exactly one line. A queued bill becomes a **DRAFT**
Purchase Receipt straight from the list ONLY when every check is green:
supplier matched · the single line's item is known · amounts tally · bill date
inside the window · **no duplicate of any kind, including the JV route** · an
Item Group and Reason for Purchase could be read. The draft then walks the
normal maker → L1 → L2 approval flow. **Nothing is ever submitted.** Any red
check names its reason and the bill goes through the full form instead.

## 13. Vendor payments (HDFC E-Net file)

Approved, submitted invoices with an outstanding amount can be written into the
bank's upload file (28-column RBI format, headerless, named
`8892RBI<DDMM>.<serial>`): **"I"** for HDFC-to-HDFC transfers, **"N"** (NEFT)
otherwise; beneficiary code/account/IFSC come from the Supplier master. The file
**moves no money** — it is uploaded to E-Net by the authorised person and the
bank's own approvals still apply. Drafts and paid bills are refused; a supplier
with missing bank details fails loudly, per supplier.

## 14. What this system will never do

- **Submit** any document, ever. (Quick post creates a *draft*, visibly, from
  green checks — the approval chain is untouched.)
- Choose the Item Group, or silently create items or suppliers.
- Deduct TDS, or claim GST credit, without a human click.
- Absorb an arithmetic gap the bill's own printed figures don't explain.
- Send emails or notifications — everything surfaces on screen and dashboards.
- Touch a GST ledger for an entity without GST registration.
- Move money. The payment file is typing saved, not control removed.
