# Bill OCR Items — Weekly Review
#
# Every item created from a bill scan is flagged for review (2,291 items were
# created in twelve months before this feature — friction and review are the
# guards that keep the master from regrowing that mess). This report is the
# reviewer's weekly worklist: what was created, from which bill, by whom,
# whether it has been reviewed — and its closest existing look-alikes, so a
# duplicate that slipped past the creation gate is caught here.
#
# Reviewing = opening the item and ticking "Reviewed" in its Bill OCR section;
# the row then moves out of the pending view.

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 240},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 170},
		{"label": _("Stock?"), "fieldname": "is_stock_item", "fieldtype": "Check", "width": 65},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Data", "width": 80},
		{"label": _("Created"), "fieldname": "creation_date", "fieldtype": "Date", "width": 100},
		{"label": _("Created by"), "fieldname": "owner", "fieldtype": "Data", "width": 170},
		{"label": _("Source bill"), "fieldname": "source", "fieldtype": "Data", "width": 200},
		{"label": _("Reviewed"), "fieldname": "reviewed", "fieldtype": "Check", "width": 80},
		{"label": _("Times purchased"), "fieldname": "times_used", "fieldtype": "Int", "width": 110},
		{"label": _("Looks similar to (check for duplicates)"), "fieldname": "similar", "fieldtype": "Data", "width": 340},
	]


def get_data(filters):
	conditions = {"custom_created_from_bill_ocr": 1}
	status = filters.get("status") or "Pending review"
	if status == "Pending review":
		conditions["custom_bill_ocr_reviewed"] = 0
	elif status == "Reviewed":
		conditions["custom_bill_ocr_reviewed"] = 1
	if filters.get("from_date"):
		conditions["creation"] = [">=", filters.from_date]

	items = frappe.get_all(
		"Item",
		filters=conditions,
		fields=["name", "item_name", "item_group", "is_stock_item", "stock_uom",
			"creation", "owner", "custom_bill_ocr_source", "custom_bill_ocr_reviewed"],
		order_by="creation desc",
		limit_page_length=0,
	)
	if not items:
		return []

	# How often each has actually been bought since creation — a created-and-used
	# item is probably legitimate; a created-and-never-used one deserves a look.
	usage = dict(frappe.db.sql(
		"""
		select pri.item_code, count(*)
		from `tabPurchase Receipt Item` pri
		join `tabPurchase Receipt` pr on pri.parent = pr.name
		where pr.docstatus < 2 and pri.item_code in %(codes)s
		group by pri.item_code
		""",
		{"codes": [i.name for i in items]},
	))

	# Near-matches, so a duplicate that slipped past the creation gate is caught
	# in review. Only computed for the rows on this screen (capped), because the
	# similarity scan reads the whole item master.
	from fountainhead.bill_ocr import match

	rows = []
	for i, it in enumerate(items):
		similar = ""
		if i < 100:
			try:
				cands = [c for c in match.find_similar_items(it.item_name) if c.get("item_code") != it.name]
				similar = " · ".join(
					f'{c.get("item_name") or c.get("item_code")} ({c.get("score")}%)' for c in cands[:3]
				)
			except Exception:
				similar = ""
		rows.append({
			"item_code": it.name,
			"item_group": it.item_group,
			"is_stock_item": it.is_stock_item,
			"stock_uom": it.stock_uom,
			"creation_date": it.creation.date() if it.creation else None,
			"owner": it.owner,
			"source": it.custom_bill_ocr_source or "",
			"reviewed": it.custom_bill_ocr_reviewed,
			"times_used": usage.get(it.name, 0),
			"similar": similar,
		})
	return rows
