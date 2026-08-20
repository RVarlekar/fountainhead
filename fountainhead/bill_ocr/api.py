"""The endpoint the Purchase Receipt form calls.

Contract, and the reason for it: this returns DATA. It does not create, save or
submit anything. The browser fills the form the user is already looking at, the
user checks it, the user presses Save.

That is not a workaround — `custom_item_group` and `custom_reason_for_purchase`
are mandatory on Purchase Receipt and are on no vendor bill, so anything that
tried to save a document from here would fail every time. It also keeps Vardan
sir's "nothing posts automatically" rule true by construction.
"""

import mimetypes

import frappe
from frappe import _
from frappe.utils import cint

from fountainhead.bill_ocr import extract, match, normalize

SUPPORTED_DOCTYPES = ("Purchase Receipt", "Purchase Invoice")


def _find_duplicates(supplier, bill_no):
	"""Existing Purchase Receipts / Invoices carrying this supplier + invoice no.

	Both doctypes are checked whichever one is open: the same paper bill must not
	enter as a Receipt after it already entered as an Invoice, or vice versa.
	Cancelled documents (docstatus 2) don't count.
	"""
	if not supplier or not bill_no:
		return []
	found = []
	for doctype in SUPPORTED_DOCTYPES:
		for name in frappe.get_all(
			doctype,
			filters={"supplier": supplier, "bill_no": bill_no, "docstatus": ["<", 2]},
			pluck="name",
			limit_page_length=3,
		):
			found.append({"doctype": doctype, "name": name})
	return found


def _same_day_bills(supplier, bill_date, bill_no):
	"""Other Receipts/Invoices from this supplier dated the same day, under a
	different invoice number. Cancelled documents don't count."""
	if not supplier or not bill_date:
		return []
	found = []
	for doctype in SUPPORTED_DOCTYPES:
		filters = {"supplier": supplier, "bill_date": bill_date, "docstatus": ["<", 2]}
		if bill_no:
			filters["bill_no"] = ["!=", bill_no]
		for name in frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=3):
			found.append({"doctype": doctype, "name": name})
	return found


def _load_attachment(file_url):
	"""Fetch the attached file, enforcing the caller's own read permission on it."""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(_("Could not find that attachment."))

	file_doc = frappe.get_doc("File", name)
	# Honour File's own permission logic (private files, attached-to checks).
	file_doc.check_permission("read")

	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")

	mime = mimetypes.guess_type(file_doc.file_name or file_url)[0]
	if not mime:
		frappe.throw(_("Could not tell what kind of file that is. Attach a PDF or an image."))
	return content, mime


@frappe.whitelist()
def create_item_from_bill(
	item_name,
	item_group,
	stock_uom,
	is_stock_item=1,
	description=None,
	source_note=None,
	acknowledged_similar=0,
):
	"""Create an Item from a bill line — deliberately, never casually.

	Guarded this hard because the item master is already the project's worst data
	problem: 6,141 items, **2,291 of them created in the last twelve months**, with
	typo-duplicates like "Foam Roller 6" / "Fuam Roller 6" / "Foam Roller 6 Inch"
	sitting side by side. A frictionless create button on every unmatched bill line
	would make that materially worse, and cleaning it up is already on the task list.

	So: the caller must pass `acknowledged_similar=1` before we will create anything
	that resembles an existing item. The first call returns the near-matches instead
	of creating, and the UI shows them as "did you mean?".

	Uses `insert()` so every standard ERPNext validation and hook runs — never a
	raw SQL write.
	"""
	if not frappe.has_permission("Item", "create"):
		raise frappe.PermissionError(
			_("You do not have permission to create Items. Ask someone with the "
			  "Item Manager or Purchase Master Manager role.")
		)

	item_name = (item_name or "").strip()
	if not item_name:
		frappe.throw(_("Give the item a name."))
	if not item_group or not frappe.db.exists("Item Group", item_group):
		frappe.throw(_("Choose a valid Item Group — it decides where this item is reported."))
	if not stock_uom or not frappe.db.exists("UOM", stock_uom):
		frappe.throw(_("Choose a valid Unit of Measure."))

	if frappe.db.exists("Item", item_name):
		frappe.throw(_("An item called {0} already exists — use it instead.").format(item_name))

	# Duplicate gate. Only skipped once the user has actually seen the near-matches.
	if not cint(acknowledged_similar):
		similar = match.find_similar_items(item_name)
		if similar:
			return {"created": False, "needs_confirmation": True, "similar": similar}

	doc = frappe.get_doc({
		"doctype": "Item",
		"item_code": item_name,
		"item_name": item_name,
		"item_group": item_group,
		"stock_uom": stock_uom,
		"is_stock_item": cint(is_stock_item),
		"description": description or item_name,
		# Tracking, so the weekly review can find everything this feature created.
		"custom_created_from_bill_ocr": 1,
		"custom_bill_ocr_source": source_note or "",
	})
	doc.insert()

	frappe.msgprint(
		_("Created item {0}. It is flagged for the weekly review of new items.").format(doc.name),
		alert=True,
	)
	return {
		"created": True,
		"item_code": doc.name,
		"item_name": doc.item_name,
		"stock_uom": doc.stock_uom,
		"is_stock_item": doc.is_stock_item,
	}


@frappe.whitelist()
def create_supplier_from_bill(supplier_name, supplier_group=None, acknowledged_similar=0):
	"""Create a Supplier from a bill, with the same duplicate discipline.

	The master already carries pairs like DEEPAK STATIONERY and DEEPAK STATIONERY
	MART, so near-matches must be seen before a new one is allowed.
	"""
	if not frappe.has_permission("Supplier", "create"):
		raise frappe.PermissionError(_("You do not have permission to create Suppliers."))

	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw(_("Give the supplier a name."))
	if frappe.db.exists("Supplier", supplier_name):
		frappe.throw(_("A supplier called {0} already exists.").format(supplier_name))

	if not cint(acknowledged_similar):
		res = match.match_supplier(supplier_name)
		similar = res.get("candidates") or []
		if similar:
			return {"created": False, "needs_confirmation": True, "similar": similar}

	doc = frappe.get_doc({
		"doctype": "Supplier",
		"supplier_name": supplier_name,
		"supplier_group": supplier_group
		or frappe.db.get_single_value("Buying Settings", "supplier_group")
		or frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
	})
	doc.insert()
	frappe.msgprint(_("Created supplier {0}.").format(doc.name), alert=True)
	return {"created": True, "supplier": doc.name}


@frappe.whitelist()
def get_creation_defaults(item_group=None, unit=None):
	"""What the create-item form should default to, given the chosen Item Group."""
	return {
		"stock": match.stock_default_for_group(item_group),
		"stock_uom": match.normalise_uom(unit),
	}


@frappe.whitelist()
def extract_bill(file_url, doctype="Purchase Receipt", company=None):
	"""Read an attached bill and return values for the form to fill in.

	Args:
		file_url: the `custom_attachment` value on the open document.
		doctype:  Purchase Receipt or Purchase Invoice.
		company:  the document's company — decides the GST treatment (see _serve).

	Returns a dict the client applies field by field. Nothing is written here.

	EVERY successful reading is cached (keyed on the file's content hash, so a
	re-upload of the same photo counts as the same bill). Reloading the page and
	re-attaching, or attaching a bill the batch queue already read, reuses the
	stored reading — the same bill is never paid for twice.

	The cache stores the RAW reading; company-dependent treatment (GST fold) and
	time-dependent warnings (a bill going stale in the queue) are applied at
	serve time, so a cached reading behaves exactly like a fresh one would today.
	"""
	cached = _cached_payload(file_url)
	if cached is not None:
		return _serve(cached, company)
	payload = _run_extraction(file_url, doctype)
	_store_cache(file_url, payload)
	return _serve(payload, company)


@frappe.whitelist()
def reread_bill(file_url, doctype="Purchase Receipt", company=None):
	"""Read the bill again from scratch, in careful mode — the dialog's reload.

	For "something looks off but I can't name it": the cache is bypassed and the
	reader is told a human flagged unspecified mistakes, so it re-verifies every
	digit and every spelling against the image instead of transcribing at normal
	pace. Costs one fresh reading; the result replaces the cached one.
	"""
	payload = _run_extraction(file_url, doctype, careful=True)
	payload.setdefault("notes", []).insert(
		0, _("Re-read from scratch in careful mode — every figure re-verified against the image.")
	)
	_store_cache(file_url, payload)
	return _serve(payload, company)


@frappe.whitelist()
def reinterpret_bill(file_url, doctype="Purchase Receipt", feedback=None, company=None):
	"""Re-read the bill with a correction the user wrote in plain English.

	This is the "no, that calculation is wrong, and here is why" path: the
	user's own words are handed to the reader as reviewer instructions, and
	the whole pipeline runs again. Costs one fresh reading (deliberately —
	the point is to get a different answer). The corrected reading replaces
	the cached one.
	"""
	feedback = (feedback or "").strip()
	if not feedback:
		frappe.throw(_("Write what is wrong first — e.g. 'the 2,250 is a 20% supervision charge on the labour total'."))
	payload = _run_extraction(file_url, doctype, feedback=feedback, careful=True)
	payload.setdefault("notes", []).insert(
		0, _("Re-read with your correction applied: “{0}”").format(feedback[:140])
	)
	_store_cache(file_url, payload)
	return _serve(payload, company)


def _entity_books_gst(company=None):
	"""Does this entity book GST as separate tax rows?

	Decided in the 19 Aug review: the school has no GST registration, takes no
	input credit, and books the GST-INCLUSIVE total (98.1% of its 3,299 submitted
	receipts carry no tax rows). Protego-side entities are registered and keep
	the breakup. The switch is a Company field so each instance/entity answers
	for itself — nothing is hard-coded to a school.
	"""
	company = (
		company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not company or not frappe.db.exists("Company", company):
		return False
	return bool(cint(frappe.db.get_value("Company", company, "custom_gst_registered") or 0))


def _serve(payload, company=None):
	"""Company- and time-dependent adjustments, applied every time a reading is
	served — fresh or cached — so the cache stays raw and reusable.

	* GST treatment (per _entity_books_gst): registered entities keep the tax
	  rows; unregistered ones get the GST folded into the item rates so the
	  document books the bill's inclusive total.
	* Late-bill warning: computed against TODAY, because a bill can sit in the
	  queue for days after it was first read.
	"""
	if not _entity_books_gst(company):
		_fold_gst_into_items(payload)
	else:
		# Registered entity, GST printed, but no account head was found to book it.
		p = payload.get("projection") or {}
		if (p.get("gst_total") or 0) > 0 and not payload.get("taxes") and not p.get("lines_tax_inclusive"):
			payload.setdefault("notes", []).insert(0, _(
				"⚠ This bill carries GST of {0}, but no GST account could be found in past "
				"receipts — add it to the Taxes table yourself, or the document will total "
				"less than the bill.").format(
				frappe.format_value(p.get("gst_total"), {"fieldtype": "Currency"}))
			)
	_late_bill_note(payload)
	return payload


def _fold_gst_into_items(payload):
	"""Fold the bill's GST (and round-off) into the item rates.

	For an entity without GST registration the tax is genuinely part of the cost
	— the pencil bought at 7.20 + 18% IS an 8.00 pencil (Chetan sir's own worked
	example, M8). So instead of tax rows, each line's rate is grossed up
	pro-rata by its share of the bill, and the items alone total the printed
	grand total. Charge rows (supervision %, freight) are left alone — they are
	usually untaxed — and any rounding residual lands on the largest line so the
	total is exact.
	"""
	totals = payload.get("totals") or {}
	proj = payload.get("projection") or {}
	target = totals.get("grand_total") or proj.get("bill_grand")
	items = payload.get("items") or []
	base = [i for i in items if not i.get("is_charge") and (i.get("amount") or 0) > 0]

	had_taxes = bool(payload.get("taxes"))
	payload["taxes"] = []

	if not target or not base:
		return

	items_total = round(sum(i.get("amount") or 0 for i in items), 2)
	extra = round(float(target) - items_total, 2)
	if abs(extra) < 0.005:
		_reproject(payload, target)
		return
	# Nothing printed says the gap is tax; folding an unexplained gap into the
	# rates would hide a misread. Only fold what the bill accounts for.
	explained = round((proj.get("gst_total") or 0) + (proj.get("round_off") or 0), 2)
	if not had_taxes and abs(extra - explained) > 1:
		_reproject(payload, target)
		return

	def set_inclusive(item, amount):
		qty = item.get("quantity") or 1
		item["amount"] = round(amount, 2)
		item["rate"] = round(amount / qty, 6) if qty else round(amount, 2)

	snapshot = {id(i): i.get("amount") or 0 for i in base}
	base_total = sum(snapshot.values())
	largest = max(base, key=lambda i: snapshot[id(i)])
	remaining = extra
	for item in base:
		if item is largest:
			continue
		share = round(extra * (snapshot[id(item)] / base_total), 2)
		set_inclusive(item, snapshot[id(item)] + share)
		remaining = round(remaining - share, 2)
	set_inclusive(largest, snapshot[id(largest)] + remaining)

	_reproject(payload, target)
	payload["projection"]["gst_in_rates"] = True
	payload.setdefault("notes", []).append(_(
		"This company books GST-inclusive costs (no GST registration), so the bill's GST "
		"of {0} was folded into the item rates instead of separate tax rows — the rows "
		"book the printed total of {1}. The printed breakup stays above for checking."
	).format(
		frappe.format_value(proj.get("gst_total") or extra, {"fieldtype": "Currency"}),
		frappe.format_value(target, {"fieldtype": "Currency"}),
	))


def _reproject(payload, target):
	"""Recompute the tally projection after items changed and tax rows left."""
	items = payload.get("items") or []
	items_total = round(sum(i.get("amount") or 0 for i in items), 2)
	proj = payload.setdefault("projection", {})
	proj["items_total"] = items_total
	proj["expected_grand"] = items_total
	proj["round_off"] = 0
	proj["lines_tax_inclusive"] = True  # the rows now carry the tax inside them
	proj["tallies"] = target is not None and abs(items_total - float(target)) <= 1


def _late_bill_note(payload):
	"""Warn when the bill is dated outside the accepted window.

	Decided in the 19 Aug review: the current and the previous month pass
	(July's end-of-month purchases arrive as bills in August); anything older
	must reach someone's attention — late bills also complicate TDS timing.
	Configurable: `bench set-config bill_ocr_late_bill_months <n>` (default 1).
	No email is sent — the warning shows here and the row stays visible for the
	manager's dashboard. Computed at serve time, against today.
	"""
	from frappe.utils import add_months, get_first_day, getdate, nowdate

	bill_date = (payload.get("fields") or {}).get("bill_date")
	if not bill_date:
		return
	try:
		d = getdate(bill_date)
	except Exception:
		return
	today = getdate(nowdate())
	months = cint(frappe.conf.get("bill_ocr_late_bill_months") or 1)
	window_start = get_first_day(add_months(today, -months))
	notes = payload.setdefault("notes", [])
	if d < window_start:
		notes.insert(0, _(
			"⚠ This invoice is dated {0} — older than the current + previous month window. "
			"Late bills need someone's attention (they also affect TDS timing): make sure "
			"the right person knows before this is entered."
		).format(frappe.format_value(str(d), {"fieldtype": "Date"})))
	elif d > today:
		notes.insert(0, _(
			"⚠ This invoice is dated {0} — a FUTURE date. Check the date was read correctly."
		).format(frappe.format_value(str(d), {"fieldtype": "Date"})))


def _content_hash(file_url):
	"""The File's content hash — identical bytes give the same hash even when a
	re-upload was given a different file name/URL."""
	try:
		return frappe.db.get_value("File", {"file_url": file_url}, "content_hash")
	except Exception:
		return None


def _cached_payload(file_url):
	"""A stored reading for this bill, by exact file URL or by content hash."""
	import json

	if not frappe.db.exists("DocType", "Bill OCR Upload"):
		return None

	# "Receipt created" rows still hold a perfectly good reading — re-attaching
	# that bill (e.g. on the matching Purchase Invoice) must stay free too.
	done_statuses = ["in", ["Read", "Receipt created"]]
	row = frappe.db.get_value(
		"Bill OCR Upload",
		{"bill_file": file_url, "status": done_statuses},
		["name", "extraction_json"],
		as_dict=True,
	)
	if not row:
		chash = _content_hash(file_url)
		if chash:
			row = frappe.db.get_value(
				"Bill OCR Upload",
				{"content_hash": chash, "status": done_statuses},
				["name", "extraction_json"],
				as_dict=True,
			)
	if not row or not row.extraction_json:
		return None
	try:
		payload = json.loads(row.extraction_json)
	except ValueError:
		return None
	# Permission flags are per-user; never serve another user's.
	payload["can_create_item"] = bool(frappe.has_permission("Item", "create"))
	payload["can_create_supplier"] = bool(frappe.has_permission("Supplier", "create"))

	# The learned-item memory moves on after a reading is cached — refresh it, so
	# something the user taught YESTERDAY applies to a bill cached LAST WEEK.
	for it in payload.get("items") or []:
		if it.get("item_code"):
			continue
		for text in (it.get("description"), it.get("description_en")):
			key = " ".join(str(text or "").split()).casefold()[:500]
			if len(key) < 4:
				continue
			code = frappe.db.get_value("Bill OCR Item Map", {"normalized_text": key}, "item_code")
			if code and frappe.db.get_value("Item", code, "disabled") == 0:
				it["item_code"] = code
				(it.setdefault("candidates", [])).insert(0, {
					"item_code": code,
					"item_name": frappe.db.get_value("Item", code, "item_name") or code,
					"score": 100.0, "seen_before": True, "times_used": 0, "basis": "learned",
				})
				break

	# Readings cached before the taxes-table feature lack the tax rows — rebuild
	# them from the stored totals so old caches behave like fresh reads.
	if "taxes" not in payload:
		t = payload.get("totals") or {}
		taxes = []
		account_head = frappe.db.get_value(
			"Purchase Taxes and Charges",
			{"parenttype": "Purchase Receipt", "account_head": ["like", "%GST%"]},
			"account_head",
		)
		if account_head:
			for label, amount in (("CGST", t.get("cgst")), ("SGST", t.get("sgst")), ("IGST", t.get("igst"))):
				if amount:
					taxes.append({
						"charge_type": "Actual", "account_head": account_head,
						"description": _("{0} as printed on the bill").format(label),
						"tax_amount": amount,
					})
			if taxes and t.get("round_off"):
				taxes.append({
					"charge_type": "Actual", "account_head": account_head,
					"description": _("Round off as printed on the bill"),
					"tax_amount": t.get("round_off"),
				})
		payload["taxes"] = taxes

	payload.setdefault("notes", []).append(
		_("Reused the stored reading ({0}) — no new reading was paid for.").format(row.name)
	)
	return payload


def _store_cache(file_url, payload):
	"""Persist a reading so re-attaching this bill is instant and free.

	Reuses the Bill OCR Upload queue as the store — every read bill therefore
	also appears in the queue list, which doubles as an audit trail of what has
	been read and when. A cache failure must never break the extraction itself,
	hence the broad guard.
	"""
	import json

	try:
		if not frappe.db.exists("DocType", "Bill OCR Upload"):
			return
		name = frappe.db.get_value("Bill OCR Upload", {"bill_file": file_url}, "name")
		doc = (
			frappe.get_doc("Bill OCR Upload", name)
			if name
			else frappe.new_doc("Bill OCR Upload")
		)
		if not name:
			doc.bill_file = file_url
		fields = payload.get("fields") or {}
		totals = payload.get("totals") or {}
		# A row whose receipt already exists keeps that status — a re-read must
		# not pull a processed bill back into the working list.
		if doc.status != "Receipt created":
			doc.status = "Read"
		doc.error_message = ""
		doc.vendor_name = (payload.get("vendor_name_on_bill") or "")[:140]
		doc.supplier = fields.get("supplier")
		doc.bill_no = (fields.get("bill_no") or "")[:140]
		doc.bill_date = fields.get("bill_date")
		doc.grand_total = totals.get("grand_total")
		doc.lines_count = len(payload.get("items") or [])
		doc.content_hash = _content_hash(file_url)
		doc.extraction_json = json.dumps(payload, ensure_ascii=False, default=str)
		doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Bill OCR — cache store failed", message=frappe.get_traceback())


@frappe.whitelist()
def remember_item_choice(description, item_code, description_en=None):
	"""Learn from a user's pick: this exact bill wording means that item.

	Called when the user CLICKS a candidate — never from an automatic match, so
	the memory only ever contains human decisions. Next time a line matches word
	for word (case/whitespace-insensitive), the item is filled in directly.
	"""
	from fountainhead.fountainhead.doctype.bill_ocr_item_map.bill_ocr_item_map import normalise_key

	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Unknown item {0}.").format(item_code))

	saved = []
	for text in {description, description_en}:
		key = normalise_key(text)
		if not key or len(key) < 4:
			continue
		name = frappe.db.get_value("Bill OCR Item Map", {"normalized_text": key}, "name")
		if name:
			doc = frappe.get_doc("Bill OCR Item Map", name)
			doc.item_code = item_code
			doc.times_used = (doc.times_used or 0) + 1
		else:
			doc = frappe.new_doc("Bill OCR Item Map")
			doc.normalized_text = key
			doc.original_text = text
			doc.item_code = item_code
			doc.times_used = 1
		doc.last_used = frappe.utils.today()
		doc.save(ignore_permissions=True)
		saved.append(doc.name)
	return {"learned": saved}


def check_against_bill(doc, method=None):
	"""On save of a Purchase Receipt/Invoice with an attached bill: does the
	document's grand total tally with what the bill printed?

	A WARNING, not a block — Vardan sir's rule is that the human decides. But the
	human should never save a mismatched total without having been told.
	"""
	import json

	if not doc.get("custom_attachment"):
		return
	try:
		row = frappe.db.get_value(
			"Bill OCR Upload",
			{"bill_file": doc.custom_attachment, "status": ["in", ["Read", "Receipt created"]]},
			["extraction_json"],
		)
		if not row:
			return
		bill_total = ((json.loads(row) or {}).get("totals") or {}).get("grand_total")
		if not bill_total:
			return
		diff = round(float(doc.grand_total or 0) - float(bill_total), 2)
		if abs(diff) > 1:
			frappe.msgprint(
				_("⚠ This document totals {0}, but the attached bill printed {1} — a difference "
				  "of {2}. Check the item amounts, charges and taxes before submitting.").format(
					frappe.format_value(doc.grand_total, {"fieldtype": "Currency"}),
					frappe.format_value(bill_total, {"fieldtype": "Currency"}),
					frappe.format_value(abs(diff), {"fieldtype": "Currency"}),
				),
				indicator="orange",
				title=_("Bill total does not tally"),
			)
	except Exception:
		frappe.log_error(title="Bill OCR — tally check failed", message=frappe.get_traceback())


def mark_upload_processed(doc, method=None):
	"""After a Purchase Receipt/Invoice with an attached bill is saved: move the
	matching queue row to "Receipt created" and link the document.

	This is what lets the queue list hide finished work — "जिसका processing पूरा
	खत्म हो गया, वो नहीं देखूं" (19 Aug). A failure here must never block the save.
	"""
	if not doc.get("custom_attachment"):
		return
	try:
		name = frappe.db.get_value("Bill OCR Upload", {"bill_file": doc.custom_attachment}, "name")
		if not name:
			chash = _content_hash(doc.custom_attachment)
			if chash:
				name = frappe.db.get_value("Bill OCR Upload", {"content_hash": chash}, "name")
		if name:
			frappe.db.set_value(
				"Bill OCR Upload",
				name,
				{"status": "Receipt created", "created_document": f"{doc.doctype} {doc.name}"},
				update_modified=False,
			)
	except Exception:
		frappe.log_error(title="Bill OCR — mark processed failed", message=frappe.get_traceback())


def _run_extraction(file_url, doctype="Purchase Receipt", feedback=None, careful=False):
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Bill OCR does not handle {0}.").format(doctype))

	# The caller must be someone who could legitimately create this document.
	if not frappe.has_permission(doctype, "create"):
		raise frappe.PermissionError(_("You are not allowed to create {0}.").format(doctype))

	file_bytes, mime = _load_attachment(file_url)

	raw, usage = extract.read_bill(file_bytes, mime, feedback=feedback, careful=careful)
	data, notes = normalize.normalize(raw)

	# Charges outside the line items — supervision %, freight, handling. These are
	# part of the printed grand total, so they MUST become rows too: dropping them
	# is how a 13,500 bill turned into an 11,250 Purchase Receipt (the Santosh Devi
	# case — a 20% supervision charge of 2,250 was read correctly and then lost).
	for charge in data.get("otherCharges") or []:
		amount = charge.get("amount")
		if not amount:
			continue
		desc = charge.get("description") or _("Additional charge on the bill")
		(data.setdefault("lines", [])).append({
			"description": desc,
			"descriptionEn": desc,
			"isTranslated": False,
			"isCharge": True,
			"hsnSac": None,
			"quantity": 1.0,
			"unit": None,
			"rate": amount,
			"lineAmount": amount,
		})
		notes.append(
			_("“{0}” ({1}) is a charge on top of the line items — added as its own row so the "
			  "document total matches the bill.").format(
				str(desc)[:60], frappe.format_value(amount, {"fieldtype": "Currency"})
			)
		)

	# Prefer the English rendering of the vendor name — the supplier master is Latin,
	# so a Gujarati name can only match through its translation.
	vendor_for_match = data.get("vendorNameEn") or data.get("vendorName")
	supplier = match.match_supplier(vendor_for_match, data.get("vendorGstin"))
	if not supplier["supplier"]:
		notes.append(
			_("No supplier matched {0} — pick one, or create it deliberately.").format(
				vendor_for_match or _("the name on the bill")
			)
		)
	elif supplier["method"] == "fuzzy_name":
		notes.append(
			_("Supplier matched by name similarity ({0}%) — please confirm it is right.").format(
				supplier["confidence"]
			)
		)

	# Duplicate check: the same supplier presenting the same invoice number is the
	# classic double-entry — the same paper bill keyed twice and paid twice. Cheap
	# to catch here, expensive to unwind after payment.
	duplicates = _find_duplicates(supplier["supplier"], data.get("invoiceNumber"))
	for dup in duplicates:
		notes.insert(
			0,
			_("⚠ Possible duplicate: {0} {1} already carries invoice no {2} for this supplier. "
			  "Check before saving — if this is genuinely a different bill, you can ignore "
			  "this warning and continue.").format(dup["doctype"], dup["name"], data.get("invoiceNumber")),
		)

	# Same supplier, same day, a DIFFERENT bill number — the real case behind this
	# (raised 19 Aug): the same vendor billed the same printing twice in one day,
	# morning and evening, and it was only caught by a manual investigation. Cheap
	# to surface here; the human decides whether it is genuine.
	for dup in _same_day_bills(supplier["supplier"], data.get("invoiceDate"), data.get("invoiceNumber")):
		notes.insert(
			0,
			_("⚠ {0} {1} is from the same supplier on the same date ({2}) under a different "
			  "invoice number. Two bills from one vendor in one day can be the same purchase "
			  "billed twice — compare the items before saving. Ignore this if both are genuine.").format(
				dup["doctype"], dup["name"], data.get("invoiceDate")),
		)

	item_group = match.suggest_item_group(supplier["supplier"])
	items = match.match_items(
		data.get("lines") or [],
		supplier["supplier"],
		item_group_hint=(item_group or {}).get("item_group"),
	)

	learned = sum(1 for i in items if i.get("item_code"))
	unmatched = sum(1 for i in items if not i.get("item_code") and not i.get("candidates"))
	if learned:
		notes.append(
			_("{0} line(s) filled automatically — you picked the same item for this exact "
			  "wording before.").format(learned)
		)
	if unmatched:
		notes.append(
			_("{0} of {1} bill lines have no similar item — pick or create those yourself. "
			  "Quantity and rate are filled in from the bill either way.").format(
				unmatched, len(items)
			)
		)

	# GST does not live in item rows — ERPNext totals it from the Purchase Taxes
	# and Charges table, and leaving that empty is why a 28,558 bill produced a
	# 24,202 document. Build the tax rows here, with the account head this
	# company's own receipts already use ("GST Account - FS", 28 uses), so the
	# grand total matches the bill. Skipped when the line amounts are already
	# tax-inclusive — the tax is inside the rows then, and adding it again would
	# double-count.
	taxes = []
	if not data.get("linesTaxInclusive"):
		account_head = frappe.db.get_value(
			"Purchase Taxes and Charges",
			{"parenttype": "Purchase Receipt", "account_head": ["like", "%GST%"]},
			"account_head",
		)
		gst_rows = [
			("CGST", data.get("cgstAmount")),
			("SGST", data.get("sgstAmount")),
			("IGST", data.get("igstAmount")),
			("Cess", data.get("cessAmount")),
		]
		if account_head and any(a for _l, a in gst_rows):
			for label, amount in gst_rows:
				if amount:
					taxes.append({
						"charge_type": "Actual",
						"account_head": account_head,
						"description": _("{0} as printed on the bill").format(label),
						"tax_amount": amount,
					})
			# The printed round-off, so the document lands on the bill's exact figure.
			roff = data.get("roundOff")
			if roff:
				companies = frappe.get_all("Company", pluck="name", limit_page_length=2)
				roff_account = (
					frappe.db.get_value("Company", companies[0], "round_off_account")
					if len(companies) == 1 else None
				)
				taxes.append({
					"charge_type": "Actual",
					"account_head": roff_account or account_head,
					"description": _("Round off as printed on the bill"),
					"tax_amount": roff,
				})
			# Which entities actually BOOK these rows is decided at serve time
			# (_serve): unregistered ones get the GST folded into the rates
			# instead, per the 19 Aug decision. The raw reading always carries
			# the rows so the cache serves both kinds of entity.

	# What will ERPNext total once these rows are in, and does that tally with the
	# bill? Items carry the pre-tax amounts (or tax-inclusive ones, flagged); GST
	# goes through the taxes table separately.
	items_total = round(sum(i.get("amount") or 0 for i in items), 2)
	gst_total = round(sum(filter(None, [
		data.get("cgstAmount"), data.get("sgstAmount"),
		data.get("igstAmount"), data.get("cessAmount"),
	])), 2)
	round_off = data.get("roundOff") or 0
	bill_grand = data.get("totalInvoiceValue")
	inclusive = bool(data.get("linesTaxInclusive"))
	expected = round(items_total + (0 if inclusive else gst_total) + round_off, 2)
	tallies = bill_grand is not None and abs(expected - bill_grand) <= 1
	pages = data.get("pageSummaries") or []
	if bill_grand is not None and not tallies:
		notes.insert(0, _(
			"⚠ The rows below will total {0}{1}, but the bill prints {2} — a gap of {3}. "
			"Something on the bill was misread or missed. Use the correction box to say what, "
			"in plain words, and it will be re-read."
		).format(
			frappe.format_value(items_total, {"fieldtype": "Currency"}),
			(" + GST " + frappe.format_value(gst_total, {"fieldtype": "Currency"})) if gst_total and not inclusive else "",
			frappe.format_value(bill_grand, {"fieldtype": "Currency"}),
			frappe.format_value(abs(round((expected - bill_grand), 2)), {"fieldtype": "Currency"}),
		))
		# On a multi-page scan, say what each page held — "page 1 totals 6,300,
		# page 2 totals 14,900, still short" is what lets a human realise the
		# scan is missing a page (caught exactly this way in the 19 Aug demo).
		if pages:
			per_page = "; ".join(
				_("page {0}: {1} line(s) totalling {2}").format(
					p.get("page"),
					p.get("lineCount") or "?",
					frappe.format_value(p.get("itemsSubtotal"), {"fieldtype": "Currency"})
					if p.get("itemsSubtotal") is not None else "?",
				)
				for p in pages
			)
			notes.insert(1, _(
				"Read {0} page(s) — {1}. If the paper bill has more pages than were scanned "
				"(check for a printed \"page X of Y\"{2}), a page is missing from the scan: "
				"rescan the full bill and attach it again."
			).format(
				len(pages), per_page,
				_(" — this bill prints “{0}”").format(data.get("pageCountPrinted"))
				if data.get("pageCountPrinted") else "",
			))

	return {
		"taxes": taxes,
		"projection": {
			"items_total": items_total,
			"gst_total": gst_total,
			"round_off": round_off,
			"expected_grand": expected,
			"bill_grand": bill_grand,
			"tallies": tallies,
			"lines_tax_inclusive": inclusive,
			"pages": pages,
			"page_count_printed": data.get("pageCountPrinted"),
		},
		"fields": {
			# Straight off the bill — these are the ones the user retypes today.
			"bill_no": data.get("invoiceNumber"),
			"bill_date": data.get("invoiceDate"),
			"supplier": supplier["supplier"],
		},
		"supplier": supplier,
		"totals": {
			"taxable_value": data.get("taxableValue"),
			"cgst": data.get("cgstAmount"),
			"sgst": data.get("sgstAmount"),
			"igst": data.get("igstAmount"),
			"round_off": data.get("roundOff"),
			"grand_total": data.get("totalInvoiceValue"),
		},
		"items": items,
		# Offered, never applied. This field decides who approves the document.
		"suggestions": {
			"custom_item_group": item_group,
			"expense_category": data.get("expenseCategory"),
		},
		"vendor_name_on_bill": data.get("vendorName"),
		"vendor_name_english": data.get("vendorNameEn"),
		"can_create_item": bool(frappe.has_permission("Item", "create")),
		"can_create_supplier": bool(frappe.has_permission("Supplier", "create")),
		"notes": notes,
		"usage": usage,
	}


@frappe.whitelist()
def read_upload(name):
	"""Read one queued bill (a Bill OCR Upload) and store the result on it.

	Called sequentially from the browser for each Pending row — deliberately not
	a background job, so the batch works the same on a dev bench (no workers)
	and under supervisor, shows progress, and can be stopped mid-way.

	Errors are RECORDED on the row rather than raised, so one unreadable photo
	doesn't stop the rest of the batch.
	"""
	import json

	doc = frappe.get_doc("Bill OCR Upload", name)
	doc.check_permission("write")

	if doc.status in ("Read", "Receipt created") and doc.extraction_json:
		return {"name": doc.name, "status": doc.status, "skipped": True}

	try:
		payload = _cached_payload(doc.bill_file) or _run_extraction(
			doc.bill_file, doc.target_doctype or "Purchase Receipt"
		)
	except Exception as e:
		doc.status = "Error"
		doc.error_message = str(e)[:500]
		doc.save()
		return {"name": doc.name, "status": "Error", "error": doc.error_message}

	fields = payload.get("fields") or {}
	totals = payload.get("totals") or {}
	doc.status = "Read"
	doc.error_message = ""
	doc.vendor_name = (payload.get("vendor_name_on_bill") or "")[:140]
	doc.supplier = fields.get("supplier")
	doc.bill_no = (fields.get("bill_no") or "")[:140]
	doc.bill_date = fields.get("bill_date")
	doc.grand_total = totals.get("grand_total")
	doc.lines_count = len(payload.get("items") or [])
	doc.content_hash = _content_hash(doc.bill_file)
	doc.extraction_json = json.dumps(payload, ensure_ascii=False, default=str)
	doc.save()

	return {
		"name": doc.name,
		"status": "Read",
		"vendor": doc.vendor_name,
		"supplier": doc.supplier,
		"bill_no": doc.bill_no,
		"grand_total": doc.grand_total,
	}
