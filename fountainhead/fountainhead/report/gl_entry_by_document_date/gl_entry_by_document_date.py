# GL Entry by Document Date
#
# The problem this replaces: every standard report keys off posting_date, so a
# bill dated 2 July that was entered on 13 July reports in the wrong period —
# accounts hand-built ~11 workaround reports on GL Entry to see the real dates.
#
# This report keys off THE DOCUMENT'S OWN DATE, collapsed into one column:
#   Purchase Invoice  -> bill_date        (the supplier's invoice date)
#   Journal Entry     -> cheque_date      (the instrument/reference date)
#   Payment Entry     -> reference_date   (the cheque/transaction date)
#   everything else   -> posting_date
# each falling back to posting_date when the source date is empty.
#
# The from/to filter runs on that document date (switchable back to posting
# date), so "show me July" means July by the paper, not July by data entry.
# Filtered to a bank account it doubles as the bank report on reference date.

import frappe
from frappe import _

DOC_DATE_SQL = """
	coalesce(
		case gle.voucher_type when 'Purchase Invoice' then pi.bill_date end,
		case gle.voucher_type when 'Journal Entry' then je.cheque_date end,
		case gle.voucher_type when 'Payment Entry' then pe.reference_date end,
		gle.posting_date
	)
"""

REF_NO_SQL = """
	coalesce(
		case gle.voucher_type when 'Purchase Invoice' then pi.bill_no end,
		case gle.voucher_type when 'Journal Entry' then je.cheque_no end,
		case gle.voucher_type when 'Payment Entry' then pe.reference_no end
	)
"""


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Document Date"), "fieldname": "doc_date", "fieldtype": "Date", "width": 105},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 105},
		{"label": _("Days Late"), "fieldname": "days_late", "fieldtype": "Int", "width": 80},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 130},
		{"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link",
		 "options": "voucher_type", "width": 170},
		{"label": _("Bill / Ref No"), "fieldname": "ref_no", "fieldtype": "Data", "width": 120},
		{"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 220},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 180},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 120},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 120},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 260},
	]


def get_data(filters):
	date_field = DOC_DATE_SQL if (filters.get("date_basis") or "Document Date") == "Document Date" \
		else "gle.posting_date"

	conditions = ["gle.is_cancelled = 0"]
	values = {
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
	}
	if filters.get("from_date"):
		conditions.append(f"{date_field} >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append(f"{date_field} <= %(to_date)s")
	if filters.get("company"):
		conditions.append("gle.company = %(company)s")
		values["company"] = filters.company
	if filters.get("account"):
		conditions.append("gle.account = %(account)s")
		values["account"] = filters.account
	if filters.get("party"):
		conditions.append("gle.party = %(party)s")
		values["party"] = filters.party
	if filters.get("voucher_type"):
		conditions.append("gle.voucher_type = %(voucher_type)s")
		values["voucher_type"] = filters.voucher_type

	rows = frappe.db.sql(
		f"""
		select
			{DOC_DATE_SQL} as doc_date,
			gle.posting_date,
			datediff(gle.posting_date, {DOC_DATE_SQL}) as days_late,
			gle.voucher_type, gle.voucher_no,
			{REF_NO_SQL} as ref_no,
			gle.account,
			coalesce(gle.party, gle.against) as party,
			gle.debit, gle.credit,
			left(gle.remarks, 140) as remarks
		from `tabGL Entry` gle
		left join `tabPurchase Invoice` pi
			on gle.voucher_type = 'Purchase Invoice' and pi.name = gle.voucher_no
		left join `tabJournal Entry` je
			on gle.voucher_type = 'Journal Entry' and je.name = gle.voucher_no
		left join `tabPayment Entry` pe
			on gle.voucher_type = 'Payment Entry' and pe.name = gle.voucher_no
		where {" and ".join(conditions)}
		order by {date_field}, gle.voucher_no
		""",
		values,
		as_dict=True,
	)

	for r in rows:
		# A negative gap means the paper is dated after entry — worth seeing too,
		# but zero-gap noise is hidden so late rows stand out.
		if not r.days_late:
			r.days_late = None
	return rows
