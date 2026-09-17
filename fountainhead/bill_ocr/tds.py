"""TDS engine — computes and SUGGESTS, never silently deducts.

Built to the spec Tejas Patel mailed on 26 Aug 2026 ("TDS Auto-Deduction Rules –
Tax Year 2026-27") plus the sittings' clarifications:

* Rules live in the `Bill TDS Rule` doctype — data, not code — so accounts can
  change a rate or threshold without a deployment (spec §12), and next year's
  rules NEVER touch entries already booked (Krunal sir's no-retroactivity check:
  rules carry effective dates; computation reads the rule as on the bill date).
* TDS is determined from the NATURE of the expense + vendor type + section +
  threshold — never from a ledger name (Tejas bhai's mail, 1 Sept).
* Threshold logic (spec §3–§6): never deduct just because the vendor has a TDS
  category; track the vendor-wise cumulative within the financial year; once
  crossed, every later bill that year is subject; the crossing bill follows the
  rule's own treatment (full amount vs only the excess).
* TDS is computed on the GST-EXCLUSIVE base (spec §7).
* Missing/invalid PAN → the higher rate, and the bill is flagged (spec §8).
* Posting side (Ankit Patel, 2 Sept): one liability ledger PER SECTION —
  "TDS Payable – 194J", "TDS Payable – 194C", "TDS Payable – 192B" and so on;
  TDS is calculated & deducted AT BILL BOOKING, same day.
* The full working (spec §10) is always shown: section, rate, previous
  cumulative, current bill, threshold, TDS amount, net payable, and the reason.

The Purchase Invoice hook only ever msgprints the working and lets the human
apply it — one click adds the deduction row. Vardan sir's no-auto-posting rule
stays intact: a suggestion the maker did not accept changes nothing.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate


PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _fy_bounds(date):
	"""Indian financial year containing `date` → (start, end)."""
	d = getdate(date)
	year = d.year if d.month >= 4 else d.year - 1
	return getdate(f"{year}-04-01"), getdate(f"{year + 1}-03-31")


def _rule_for(section, on_date):
	"""The Bill TDS Rule effective for this section on this date.

	Rules are versioned by effective_from — the rule used is the latest one that
	had already come into force on the BILL date, so a future rule change can
	never rewrite an old computation (no retroactivity).
	"""
	rows = frappe.get_all(
		"Bill TDS Rule",
		filters={"section": section, "disabled": 0,
		         "effective_from": ["<=", str(getdate(on_date))]},
		fields=["*"], order_by="effective_from desc", limit_page_length=1,
	)
	return rows[0] if rows else None


def _cumulative_base(supplier, company, fy_start, fy_end, exclude_invoice=None):
	"""This supplier's billing already booked in the window — BOTH routes.

	* Submitted Purchase Invoices' base_net_total (the GST-exclusive figure).
	* Journal-Voucher bookings (the imprest route): the supplier's CREDIT side on
	  submitted JEs — an expense-Dr/supplier-Cr voucher credits the vendor with
	  the bill amount. Without this, a vendor billed mostly through JVs would
	  never appear to cross a threshold.
	"""
	cond = "and pi.name != %(exclude)s" if exclude_invoice else ""
	args = {"supplier": supplier, "company": company, "fy_start": str(fy_start),
	        "fy_end": str(fy_end), "exclude": exclude_invoice or ""}
	rows = frappe.db.sql(
		f"""
		select ifnull(sum(pi.base_net_total), 0)
		from `tabPurchase Invoice` pi
		where pi.docstatus = 1 and pi.supplier = %(supplier)s and pi.company = %(company)s
		  and pi.posting_date between %(fy_start)s and %(fy_end)s {cond}
		""",
		args,
	)
	pi_total = flt(rows[0][0]) if rows else 0.0
	je_rows = frappe.db.sql(
		"""
		select ifnull(sum(jea.credit_in_account_currency), 0)
		from `tabJournal Entry Account` jea
		join `tabJournal Entry` je on je.name = jea.parent
		where je.docstatus = 1 and je.company = %(company)s
		  and je.posting_date between %(fy_start)s and %(fy_end)s
		  and jea.party_type = 'Supplier' and jea.party = %(supplier)s
		""",
		args,
	)
	je_total = flt(je_rows[0][0]) if je_rows else 0.0
	return pi_total + je_total


@frappe.whitelist()
def compute_tds(supplier, company, taxable_amount, section=None, bill_date=None, exclude_invoice=None):
	"""The full TDS working for one bill — spec §10's approval-screen breakdown.

	Returns a dict with every figure named; `applicable` says whether a deduction
	is due, `reason` says why or why not, in words a checker can read out.
	"""
	frappe.has_permission("Purchase Invoice", "read", throw=True)

	taxable_amount = flt(taxable_amount)
	bill_date = bill_date or nowdate()
	section = section or frappe.db.get_value("Supplier", supplier, "custom_tds_section")
	if not section:
		return {"applicable": False, "section": None,
		        "reason": _("No TDS section is set on this supplier — nothing to compute.")}

	rule = _rule_for(section, bill_date)
	if not rule:
		return {"applicable": False, "section": section,
		        "reason": _("No TDS rule is effective for section {0} on {1} — "
		                    "add one in Bill TDS Rule.").format(section, bill_date)}

	vendor_type = frappe.db.get_value("Supplier", supplier, "custom_vendor_type") or "Company"
	pan = (frappe.db.get_value("Supplier", supplier, "custom_pan") or "").strip().upper()
	pan_ok = bool(PAN_RE.match(pan))

	rate = flt(rule.rate)
	if vendor_type in ("Individual", "HUF") and flt(rule.rate_individual_huf):
		rate = flt(rule.rate_individual_huf)
	rate_reason = ""
	if not pan_ok:
		rate = max(rate, flt(rule.rate_no_pan) or 20.0)
		rate_reason = _(" — HIGHER RATE: supplier PAN is {0}").format(
			_("missing") if not pan else _("invalid ({0})").format(pan))

	# 194I-type rules test the aggregate PER MONTH/part-month; everything else
	# per financial year. The rule says which (threshold_is_monthly).
	if cint(rule.get("threshold_is_monthly")):
		d = getdate(bill_date)
		win_start = getdate(f"{d.year}-{d.month:02d}-01")
		win_end = frappe.utils.get_last_day(d)
		window_label = _("month {0}").format(d.strftime("%b %Y"))
	else:
		win_start, win_end = _fy_bounds(bill_date)
		window_label = _("FY")
	prev_cum = _cumulative_base(supplier, company, win_start, win_end, exclude_invoice)
	cum = round(prev_cum + taxable_amount, 2)
	fy_start, fy_end = _fy_bounds(bill_date)

	single = flt(rule.threshold_single)
	aggregate = flt(rule.threshold_aggregate)
	crossed_single = bool(single and taxable_amount > single)
	crossed_aggregate = bool(aggregate and cum > aggregate)
	already_over = bool(aggregate and prev_cum > aggregate)

	applicable = crossed_single or crossed_aggregate or already_over
	base = taxable_amount
	if applicable and (rule.treatment or "") == "Only the excess over the threshold" and crossed_aggregate and not already_over:
		base = round(cum - aggregate, 2)

	tds_amount = round(base * rate / 100.0, 2) if applicable else 0.0

	if already_over:
		reason = _("Aggregate threshold ({0}) was already crossed earlier this FY — every further bill is subject.").format(aggregate)
	elif crossed_aggregate:
		reason = _("This bill crosses the aggregate FY threshold ({0}): cumulative {1}.").format(aggregate, cum)
	elif crossed_single:
		reason = _("This single bill exceeds the per-bill threshold ({0}).").format(single)
	else:
		reason = _("Threshold not crossed (cumulative {0} of {1}; this bill {2} vs per-bill {3}) — NO TDS.").format(
			cum, aggregate or _("n/a"), taxable_amount, single or _("n/a"))

	return {
		"applicable": applicable,
		"section": section,
		"old_section": rule.old_section,
		"nature": rule.nature,
		"vendor_type": vendor_type,
		"pan": pan or None,
		"pan_ok": pan_ok,
		"rate": rate,
		"rate_note": rate_reason,
		"previous_cumulative": round(prev_cum, 2),
		"current_bill": taxable_amount,
		"cumulative": cum,
		"threshold_single": single,
		"threshold_aggregate": aggregate,
		"treatment": rule.treatment,
		"tds_base": base if applicable else 0,
		"tds_amount": tds_amount,
		"net_payable": round(taxable_amount - tds_amount, 2),
		"payable_account": rule.payable_account,
		"reason": reason + rate_reason,
		"fy": f"{fy_start.year}-{str(fy_end.year)[2:]}",
	}


def suggest_tds(doc, method=None):
	"""Purchase Invoice validate hook: show the TDS working when it matters.

	Suggestion only — nothing is added to the document here. The maker applies
	the deduction with the form's own button (one click), or ignores it with a
	written reason in front of the checker. Failures never block a save.
	"""
	try:
		if doc.docstatus != 0 or not doc.get("supplier"):
			return
		if not frappe.db.get_value("Supplier", doc.supplier, "custom_tds_section"):
			return
		# Already deducted on this document? Then the working was seen and used.
		for t in doc.get("taxes") or []:
			if (t.get("add_deduct_tax") == "Deduct"
					and "tds" in (t.get("account_head") or "").lower()):
				return
		result = compute_tds(
			doc.supplier, doc.company,
			flt(doc.base_net_total) or flt(doc.net_total) or flt(doc.grand_total),
			bill_date=doc.get("bill_date") or doc.get("posting_date"),
			exclude_invoice=doc.name if not doc.is_new() else None,
		)
		if not result.get("applicable"):
			return
		frappe.msgprint(
			_(
				"<b>TDS appears applicable — nothing has been deducted automatically.</b><br>"
				"Section: <b>{section}</b> (old {old_section}) · {nature}<br>"
				"Vendor type: {vendor_type} · PAN: {pan_display}<br>"
				"Previous cumulative (FY {fy}): {prev} · This bill: {cur} · Cumulative: {cum}<br>"
				"Threshold: per-bill {ts} / aggregate {ta} — {reason}<br>"
				"<b>Rate {rate}% on {base} → TDS {tds} · Net payable {net}</b><br>"
				"Credit ledger: {account}<br>"
				"Use the <b>Suggest TDS</b> button on this form to apply it as a deduction row."
			).format(
				section=result["section"], old_section=result["old_section"] or "—",
				nature=result["nature"] or "", vendor_type=result["vendor_type"],
				pan_display=(result["pan"] or _("MISSING")) + ("" if result["pan_ok"] else " ⚠"),
				fy=result["fy"], prev=result["previous_cumulative"],
				cur=result["current_bill"], cum=result["cumulative"],
				ts=result["threshold_single"] or "—", ta=result["threshold_aggregate"] or "—",
				reason=result["reason"], rate=result["rate"], base=result["tds_base"],
				tds=result["tds_amount"], net=result["net_payable"],
				account=result["payable_account"] or _("⚠ not set on the rule — set it in Bill TDS Rule"),
			),
			indicator="orange",
			title=_("TDS suggestion"),
		)
	except Exception:
		frappe.log_error(title="Bill OCR — TDS suggestion failed", message=frappe.get_traceback())


# The FY 2026-27 rule master, verbatim from Tejas Patel's 26 Aug mail (old
# sections mapped to the Income-tax Act 2025, Sec. 393 tables). Seeded once,
# idempotently, by install.after_migrate; thereafter accounts edits the doctype.
FY_2026_27_RULES = [
	dict(section="194C", old_section="194C / Sec. 393(1) T6(i)", nature="Contractor / Job Work",
	     rate=2, rate_individual_huf=1, threshold_single=30000, threshold_aggregate=100000,
	     treatment="Full amount once crossed"),
	dict(section="194J-Professional", old_section="194J / Sec. 393(1) T6(iii)", nature="Professional Services",
	     rate=10, threshold_aggregate=50000, treatment="Full amount once crossed"),
	dict(section="194J-Technical", old_section="194J / Sec. 393(1) T6(iii)", nature="Technical Services",
	     rate=2, threshold_aggregate=50000, treatment="Full amount once crossed"),
	dict(section="194I-Building", old_section="194I / Sec. 393(1) T2(ii)", nature="Rent – Land / Building / Furniture",
	     rate=10, threshold_aggregate=50000, threshold_is_monthly=1, treatment="Full amount once crossed",
	     notes="₹50,000 per month/part-month — the aggregate window is the bill's month."),
	dict(section="194I-Plant", old_section="194I / Sec. 393(1) T2(ii)", nature="Rent – Plant & Machinery",
	     rate=2, threshold_aggregate=50000, threshold_is_monthly=1, treatment="Full amount once crossed",
	     notes="₹50,000 per month/part-month — the aggregate window is the bill's month."),
	dict(section="194H", old_section="194H / Sec. 393(1) T1(ii)", nature="Commission / Brokerage",
	     rate=2, threshold_aggregate=20000, treatment="Full amount once crossed"),
	dict(section="194Q", old_section="194Q / Sec. 393(1) T8(ii)", nature="Purchase of Goods",
	     rate=0.1, threshold_aggregate=5000000, treatment="Only the excess over the threshold"),
	dict(section="194M", old_section="194M / Sec. 393(1) T6(ii)", nature="Ind/HUF – Contract / Professional / Commission",
	     rate=2, threshold_aggregate=5000000, treatment="Full amount once crossed"),
	dict(section="194R", old_section="194R / Sec. 393(1) T8(iv)", nature="Business Benefit / Perquisite",
	     rate=10, threshold_aggregate=20000, treatment="Full amount once crossed"),
	dict(section="194T", old_section="194T / Sec. 393(3) T7", nature="Payment to Partner – Salary/Bonus/Commission/Interest",
	     rate=10, threshold_aggregate=20000, treatment="Full amount once crossed"),
]


def seed_rules():
	"""Idempotent: creates each FY 2026-27 rule once; never touches an edited one."""
	if not frappe.db.exists("DocType", "Bill TDS Rule"):
		return
	for spec in FY_2026_27_RULES:
		existing = frappe.db.get_value(
			"Bill TDS Rule", {"section": spec["section"], "effective_from": "2026-04-01"},
			["name", "threshold_single", "threshold_aggregate", "threshold_is_monthly"], as_dict=True,
		)
		if existing:
			# One-time shape fix for 194I rows seeded before the monthly-window
			# field existed — touched ONLY while they still carry the exact old
			# seed values (an accounts edit is never overwritten).
			if (spec.get("threshold_is_monthly")
					and flt(existing.threshold_single) == 50000
					and not flt(existing.threshold_aggregate)
					and not cint(existing.threshold_is_monthly)):
				frappe.db.set_value("Bill TDS Rule", existing.name, {
					"threshold_single": 0,
					"threshold_aggregate": 50000,
					"threshold_is_monthly": 1,
					"notes": spec.get("notes"),
				})
			continue
		account = frappe.db.get_value(
			"Account",
			{"account_name": ["like", f"%TDS Payable%{spec['section'].split('-')[0]}%"], "disabled": 0},
			"name",
		)
		doc = frappe.get_doc({
			"doctype": "Bill TDS Rule",
			"effective_from": "2026-04-01",
			"rate_no_pan": 20,
			"payable_account": account,
			**spec,
		})
		doc.insert(ignore_permissions=True)
