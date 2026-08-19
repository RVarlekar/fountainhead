"""Deterministic clean-up of what the model returned.

The division of labour, carried over from the prototype and worth preserving:
**the model transcribes, this module judges.** Anything that can be settled by
arithmetic is settled here rather than trusted to the model — freight placement
and round-off in particular.

Everything in this file is pure: no database, no network, no clock.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

# A residual larger than this is a real discrepancy, not rounding. Never absorb it.
ROUND_OFF_CAP = 1.0

MONTHS = {
	"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
	"jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def round2(value):
	"""Half away from zero, matching the prototype's money rounding."""
	if value is None:
		return None
	return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_number(raw):
	"""Parse a printed amount: strips currency symbols, commas and spaces, and
	handles the Indian bill conventions `(-)`, a leading minus, and a trailing
	`Cr` (credit → negative) or `Dr`."""
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	s = str(raw).strip()
	if not s:
		return None

	negative = False
	if s.startswith("(") and s.endswith(")"):
		negative = True
		s = s[1:-1]
	if re.search(r"\bcr\b", s, re.I):
		negative = True
	s = re.sub(r"\b[cd]r\b", "", s, flags=re.I)
	s = re.sub(r"[^\d.\-]", "", s)
	if s.count("-"):
		negative = negative or s.lstrip().startswith("-")
		s = s.replace("-", "")
	if not s or s == ".":
		return None
	try:
		value = float(s)
	except ValueError:
		return None
	return -value if negative else value


def _expand_year(raw):
	n = int(raw)
	return 2000 + n if len(raw) <= 2 else n


def normalize_date(raw):
	"""Printed date -> (YYYY-MM-DD, ambiguous). Indian DD/MM is the default;
	a day > 12 disambiguates, and a genuinely ambiguous numeric date is flagged
	so the UI can mark it rather than silently pick one."""
	if not isinstance(raw, str):
		return None, False
	s = raw.strip()
	if not s:
		return None, False

	# YYYYMMDD
	m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
	if m:
		return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", False

	# YYYY-MM-DD
	m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
	if m:
		return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", False

	# DD-MM-YY(YY)
	m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
	if m:
		day, month = int(m.group(1)), int(m.group(2))
		year = _expand_year(m.group(3))
		ambiguous = False
		if month > 12 and day <= 12:
			day, month = month, day  # must have been MM/DD
		elif day <= 12 and month <= 12:
			ambiguous = True  # could be either; assume DD/MM
		if not (1 <= month <= 12 and 1 <= day <= 31):
			return None, False
		return f"{year}-{month:02d}-{day:02d}", ambiguous

	# 6-Apr-26 / 6 April 2026
	m = re.fullmatch(r"(\d{1,2})[-\s.]*([A-Za-z]{3,})[-\s.,]*(\d{2,4})", s)
	if m:
		month = MONTHS.get(m.group(2)[:3].lower())
		if month:
			return f"{_expand_year(m.group(3))}-{month:02d}-{int(m.group(1)):02d}", False

	return None, False


def _num(data, key):
	return parse_number(data.get(key))


def reconcile(data):
	"""Resolve freight placement and round-off by arithmetic.

	Ported from `reconcileChargesAndRoundOff`. Three jobs:

	1. Drop zero-amount and model-invented entries from otherCharges.
	2. Decide whether otherCharges sit inside or outside the taxable value, by
	   testing which reading makes the printed total reconcile.
	3. Set round-off to the residual when that residual is within genuine
	   rounding range. This both fills a missing round-off and corrects a
	   misread sub-rupee one. A residual larger than ROUND_OFF_CAP is a real
	   discrepancy and is left alone so it gets flagged, never absorbed.

	Returns a list of human-readable notes about what it changed.
	"""
	notes = []

	charges = data.get("otherCharges")
	if isinstance(charges, list):
		cleaned = [
			{"description": str(c.get("description") or ""), "amount": parse_number(c.get("amount"))}
			for c in charges
			if isinstance(c, dict) and abs(parse_number(c.get("amount")) or 0) >= 0.005
		]
		if cleaned:
			data["otherCharges"] = cleaned
		else:
			data.pop("otherCharges", None)

	total = _num(data, "totalInvoiceValue")
	if total is None:
		return notes

	components = sum(
		filter(None, [
			_num(data, "taxableValue"),
			_num(data, "cgstAmount"),
			_num(data, "sgstAmount"),
			_num(data, "igstAmount"),
			_num(data, "cessAmount"),
		])
	)
	others = data.get("otherCharges") or []
	other_sum = sum(c["amount"] for c in others if c.get("amount"))

	residual_with = round2(total - components - other_sum)
	residual_without = round2(total - components)

	residual = residual_with
	if others and abs(residual_with) > 1 and abs(residual_without) <= 1:
		# The charges are already counted inside taxableValue — the bill taxed them.
		data.pop("otherCharges", None)
		data["ancillaryCharges"] = "taxed_inclusive"
		residual = residual_without
		notes.append("Freight/packing appears to be inside the taxed value; removed the duplicate charge line.")
	elif others:
		data["ancillaryCharges"] = "untaxed_separate"

	if abs(residual) <= ROUND_OFF_CAP:
		if abs(residual) >= 0.005:
			data["roundOff"] = residual
			notes.append(f"Round-off derived as {residual:.2f} so the bill reconciles to its printed total.")
	else:
		notes.append(
			f"Components do not add up to the printed total — off by {residual:.2f}. "
			"Check the figures before saving."
		)

	return notes


# A line's qty x rate may differ from its printed amount by this much and still be
# ordinary rounding rather than a misread.
LINE_TOLERANCE = 1.0


def lines_are_tax_inclusive(data):
	"""Do the printed line amounts already include GST?

	Some bills print an "Amount" column per line that is tax-inclusive. ANJALI
	ENTERPRISE is the case that exposed this: taxable 25,000 + CGST 2,250 +
	SGST 2,250 = 29,500, and the line's Amount column reads 29,500 while its
	Price/Unit reads 25,000.

	That matters because reconcile_lines trusts the printed amount and corrects
	the rate from it. On a tax-inclusive bill that "correction" turns a correct
	rate of 25,000 into 29,500 — silently inflating the line by the tax. So this
	has to be detected first, and rate correction switched off when it is true.

	Test: the line amounts reconcile to the GRAND TOTAL rather than to the
	taxable value.
	"""
	lines = data.get("lines") or []
	amounts = [l.get("lineAmount") for l in lines if l.get("lineAmount") is not None]
	taxable = data.get("taxableValue")
	total = data.get("totalInvoiceValue")
	if not amounts or taxable is None or total is None:
		return False
	if abs(round2(total - taxable)) <= LINE_TOLERANCE:
		return False  # no tax on this bill; the question doesn't arise
	summed = round2(sum(amounts))
	return (
		abs(summed - total) <= LINE_TOLERANCE
		and abs(summed - taxable) > LINE_TOLERANCE
	)


def reconcile_lines(lines, tax_inclusive=False):
	"""Make each line's quantity, rate and amount agree with each other.

	The printed **line amount** is authoritative: it is what sums to the taxable
	value, which in turn reconciles to the printed grand total. Quantity and rate
	are the figures a reader is most likely to get wrong — adjacent columns, a
	per-unit vs per-side price, a rate printed twice.

	Real case that prompted this (PIXORA SIGNAGES, bill I/26-27/267):

	    PLAIN GLOSSY LAMINATION 100MIC   qty 548   rate 9.00   amount 9,864.00

	548 x 9 = 4,932, but the printed amount is 9,864 — and 9,864 is right, because
	it reconciles to the grand total of 11,640. The rate was misread; it is 18.00.
	Fed into the form unchecked, that produced a receipt for less than half the
	bill. Silent, and headed for a ledger.

	So where they disagree we keep quantity and the amount, and recompute the rate.
	"""
	notes = []
	for i, line in enumerate(lines, start=1):
		qty = line.get("quantity")
		rate = line.get("rate")
		amount = line.get("lineAmount")

		# Fill in whichever single value is missing.
		if amount is None and qty is not None and rate is not None:
			line["lineAmount"] = round2(qty * rate)
			continue
		if rate is None and qty not in (None, 0) and amount is not None:
			line["rate"] = round2(amount / qty)
			continue
		if qty is None and rate not in (None, 0) and amount is not None:
			line["quantity"] = round2(amount / rate)
			continue
		# Lump-sum lines — handwritten labour/service bills often print only a
		# total ("હરવાનો → 23000"). Without this, the row landed in ERPNext as
		# qty 1 × rate 0 and contributed NOTHING to the document total.
		if qty is None and rate is None and amount is not None:
			line["quantity"] = 1.0
			line["rate"] = round2(amount)
			continue

		if qty in (None, 0) or rate is None or amount is None:
			continue

		expected = round2(qty * rate)
		if abs(expected - amount) <= LINE_TOLERANCE:
			continue

		if tax_inclusive:
			# The printed amount includes GST but the rate does not, so they are
			# SUPPOSED to differ. Correcting here would inflate the rate by the tax.
			# Say so and leave the numbers alone.
			notes.append(
				f"Line {i}: the bill prints {amount:,.2f} for this line including GST, "
				f"while {qty:g} x {rate:,.2f} is the pre-tax {expected:,.2f}. Left as "
				"printed — ERPNext adds tax separately."
			)
			continue

		corrected = round2(amount / qty)
		line["rate"] = corrected
		notes.append(
			f"Line {i} ({line.get('description') or '?'} ) — {qty:g} x {rate:,.2f} is "
			f"{expected:,.2f}, but the bill prints {amount:,.2f}. Rate corrected to "
			f"{corrected:,.2f} so the line matches the bill. Please check it."
		)
	return notes


def drop_annotation_lines(data):
	"""Remove handwritten annotations that came back as line items.

	Bills in this stack carry handwritten notes — "Paper used exam",
	"Material - 6.5x6.5" — which the reader sometimes returns as extra lines
	with no amount. Left in, each one becomes a junk row in the Items table
	that the user has to delete.

	Dropping them is only safe when it is PROVEN they are not real lines: the
	lines that do carry amounts must already sum to the bill's taxable value.
	If they do, anything without an amount cannot be part of the bill's money
	and goes — with a note saying so. If they don't sum, everything is kept
	and check_line_total will warn instead; a missing amount there might be a
	real line the reader failed on.
	"""
	notes = []
	lines = data.get("lines") or []
	taxable = data.get("taxableValue")
	if taxable is None or not lines:
		return notes

	# "Unpriced" covers both shapes the reader produces for annotations: no amount
	# at all, OR an amount of zero. The same note on the same bill has come back
	# both ways on different runs — the reader is not deterministic here — and a
	# zero-rupee line is not a purchasable line in either case.
	def priced(line):
		amount = line.get("lineAmount")
		return amount is not None and abs(amount) >= 0.005

	with_amount = [l for l in lines if priced(l)]
	without = [l for l in lines if not priced(l)]
	if not without or not with_amount:
		return notes

	if abs(round2(sum(l["lineAmount"] for l in with_amount) - taxable)) <= LINE_TOLERANCE:
		data["lines"] = with_amount
		for l in without:
			desc = (l.get("description") or "?")[:60]
			notes.append(
				f'Ignored "{desc}" — it carries no amount and the priced lines already '
				"add up to the bill's taxable value, so it reads as a handwritten note, "
				"not an item."
			)
	return notes


def check_line_total(data):
	"""Warn when the line amounts don't add up to the taxable value."""
	lines = data.get("lines") or []
	amounts = [l.get("lineAmount") for l in lines if l.get("lineAmount") is not None]
	taxable = data.get("taxableValue")
	if not amounts or taxable is None:
		return []
	# On a tax-inclusive bill the lines are MEANT to exceed the taxable value by
	# exactly the tax — already explained per line, so don't warn twice.
	if data.get("linesTaxInclusive"):
		return []
	total = round2(sum(amounts))
	if abs(total - taxable) <= LINE_TOLERANCE:
		return []
	return [
		f"The {len(amounts)} line(s) add up to {total:,.2f}, but the bill's taxable value "
		f"is {taxable:,.2f} — a difference of {abs(total - taxable):,.2f}. "
		"A line may be missing or misread."
	]


def normalize(raw):
	"""Full clean-up pass. Returns (data, notes)."""
	data = dict(raw or {})
	notes = []

	iso_date, ambiguous = normalize_date(data.get("invoiceDate"))
	if iso_date:
		data["invoiceDate"] = iso_date
		if ambiguous:
			notes.append(
				f"Invoice date {raw.get('invoiceDate')!r} is ambiguous — read as DD/MM ({iso_date}). Please confirm."
			)
	else:
		data.pop("invoiceDate", None)
		if raw.get("invoiceDate"):
			notes.append(f"Could not read the invoice date {raw.get('invoiceDate')!r}. Please enter it.")

	for key in (
		"taxableValue", "cgstAmount", "sgstAmount", "igstAmount",
		"cessAmount", "roundOff", "totalInvoiceValue",
		"cgstRate", "sgstRate", "igstRate",
	):
		if key in data:
			value = parse_number(data[key])
			if value is None:
				data.pop(key, None)
			else:
				data[key] = value

	lines = []
	for line in data.get("lines") or []:
		if not isinstance(line, dict):
			continue
		original = str(line.get("description") or "").strip()
		english = str(line.get("descriptionEn") or "").strip()
		lines.append({
			"description": original,
			# The English rendering, used for item matching and for naming a new item.
			# Falls back to the original when the bill was already in English.
			"descriptionEn": english or original,
			"isTranslated": bool(english and english.casefold() != original.casefold()),
			"hsnSac": str(line.get("hsnSac") or "").strip() or None,
			"quantity": parse_number(line.get("quantity")),
			"unit": str(line.get("unit") or "").strip() or None,
			"rate": parse_number(line.get("rate")),
			"lineAmount": parse_number(line.get("lineAmount")),
		})
	data["lines"] = lines
	inclusive = lines_are_tax_inclusive(data)
	data["linesTaxInclusive"] = inclusive
	notes.extend(reconcile_lines(lines, tax_inclusive=inclusive))

	notes.extend(reconcile(data))
	notes.extend(drop_annotation_lines(data))
	notes.extend(check_line_total(data))
	return data, notes
