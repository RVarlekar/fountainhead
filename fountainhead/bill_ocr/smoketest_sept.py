def run():
	import json
	import frappe

	ok = []
	def check(label, cond, extra=""):
	    ok.append(bool(cond))
	    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra else ""))

	# 1. doctypes + seeds
	check("Bill TDS Rule doctype", frappe.db.exists("DocType", "Bill TDS Rule"))
	check("ITC Eligibility Category doctype", frappe.db.exists("DocType", "ITC Eligibility Category"))
	n_rules = frappe.db.count("Bill TDS Rule")
	check(f"TDS rules seeded (n={n_rules})", n_rules >= 10)
	n_itc = frappe.db.count("ITC Eligibility Category")
	check(f"ITC categories seeded (n={n_itc})", n_itc >= 12)

	# 2. custom fields
	for dt, f in [("Supplier", "custom_gstin"), ("Supplier", "custom_pan"),
	              ("Supplier", "custom_tds_section"), ("Supplier", "custom_beneficiary_code"),
	              ("Supplier", "custom_ifsc"), ("Purchase Invoice", "custom_gst_credit"),
	              ("Purchase Invoice", "custom_rcm")]:
	    check(f"{dt}.{f}", frappe.db.exists("Custom Field", {"dt": dt, "fieldname": f}))
	check("Upload.expense_head", frappe.db.exists("DocField", {"parent": "Bill OCR Upload", "fieldname": "expense_head"}))

	# 3. property setters (grid cleanup)
	for f in ("rejected_qty", "item_tax_template"):
	    check(f"PR Item {f} out of grid",
	          frappe.db.exists("Property Setter", {"doc_type": "Purchase Receipt Item", "field_name": f, "property": "in_list_view"}))

	# 4a. v5 — FS format: printed rates + ONE "GST" line in the items table
	#     (Metro shape: 24,202 + GST 4,356.36 + round-off -0.36 = 28,558)
	from fountainhead.bill_ocr import api
	def metro_payload():
	    return {
	        "projection": {"items_total": 24202.0, "gst_total": 4356.36, "round_off": -0.36,
	                       "bill_grand": 28558.0, "tallies": True, "lines_tax_inclusive": False},
	        "items": [
	            {"description": "A", "quantity": 10, "rate": 157, "amount": 1570.0},
	            {"description": "B", "quantity": 100, "rate": 172, "amount": 17200.0},
	            {"description": "C", "quantity": 29.048128, "rate": 187, "amount": 5432.0},
	        ],
	        "fields": {"supplier": None},
	    }
	p_v5 = metro_payload()
	api._gst_as_item_line(p_v5)
	check("v5: one GST line added (3 -> 4 items)", len(p_v5["items"]) == 4)
	gst_line = p_v5["items"][-1]
	check("v5: GST line = 4356.00 (GST + printed round-off)", abs(gst_line["amount"] - 4356.00) < 0.01,
	      str(gst_line["amount"]))
	check("v5: item rates stay as printed", p_v5["items"][0]["rate"] == 157 and p_v5["items"][0]["amount"] == 1570.0)
	check("v5: rows total the bill grand", abs(p_v5["projection"]["items_total"] - 28558.0) < 0.01)
	check("v5: no tax rows", p_v5["taxes"] == [])
	check("v5: flag set", p_v5["projection"].get("gst_as_item_line") is True)
	p_incl = {"projection": {"gst_total": 100, "round_off": 0, "lines_tax_inclusive": True},
	          "items": [{"quantity": 1, "rate": 100, "amount": 100}]}
	api._gst_as_item_line(p_incl)
	check("v5: tax-inclusive bill untouched", len(p_incl["items"]) == 1 and p_incl["items"][0]["amount"] == 100)

	# 4b. v4 fold — still the GST-entity credit-blocked path (kitchen/vehicle bills)
	payload = metro_payload()
	api._fold_gst_into_rates(payload)
	folded_total = round(sum(i["amount"] for i in payload["items"]), 2)
	check(f"bridge fold: items now total {folded_total} (bill 28558.0)", abs(folded_total - 28558.0) < 0.01)
	check("bridge fold: no charge row", payload["taxes"] == [])
	check("bridge fold: flag set", payload["projection"].get("gst_folded_into_rates") is True)
	check("bridge fold: printed rate preserved for audit", payload["items"][0].get("rate_printed") == 157)
	check("bridge fold: no extra line added", len(payload["items"]) == 3)

	# 5. narration
	p3 = {"fields": {"supplier": "Metro Printers", "bill_no": "1475"},
	      "items": [{"description_en": "Grade 1 Hindi workbook"}, {"description_en": "Grade 2 Math workbook"}]}
	api._set_narration(p3)
	check("narration built", "Metro Printers" in p3.get("narration", "") and "1475" in p3["narration"]
	      and "Details as per the attached bill." in p3["narration"], p3.get("narration", "")[:90])

	# 6. token synonyms (class -> grade)
	from fountainhead.bill_ocr import match
	check("class->grade synonym", match.tokens("Class 3 Hindi Book") == match.tokens("Grade 3 Hindi Book"))

	# 7. TDS compute — pure rule math via a temp supplier
	sup_name = "_TDS SELFTEST VENDOR"
	if not frappe.db.exists("Supplier", sup_name):
	    s = frappe.get_doc({"doctype": "Supplier", "supplier_name": sup_name,
	                        "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")})
	    s.insert(ignore_permissions=True)
	frappe.db.set_value("Supplier", sup_name, {"custom_tds_section": frappe.db.get_value("Bill TDS Rule", {"section": "194J-Professional"}, "name") and "194J-Professional" or None})
	# link field stores the docname; find it
	rule_name = frappe.db.get_value("Bill TDS Rule", {"section": "194J-Professional"}, "name")
	frappe.db.set_value("Supplier", sup_name, "custom_tds_section", rule_name)
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	from fountainhead.bill_ocr import tds
	r1 = tds.compute_tds(sup_name, company, 30000, section="194J-Professional", bill_date="2026-09-11")
	check("TDS: below threshold -> not applicable", not r1["applicable"], r1["reason"][:70])
	r2 = tds.compute_tds(sup_name, company, 60000, section="194J-Professional", bill_date="2026-09-11")
	check("TDS: over 50k -> applicable @ higher rate (no PAN -> 20%)",
	      r2["applicable"] and r2["rate"] == 20 and r2["tds_amount"] == 12000.0,
	      f"rate={r2['rate']} tds={r2['tds_amount']}")
	frappe.db.set_value("Supplier", sup_name, "custom_pan", "AADFF3677P")
	r3 = tds.compute_tds(sup_name, company, 60000, section="194J-Professional", bill_date="2026-09-11")
	check("TDS: with valid PAN -> 10%", r3["rate"] == 10 and r3["tds_amount"] == 6000.0,
	      f"rate={r3['rate']} tds={r3['tds_amount']}")
	r4 = tds.compute_tds(sup_name, company, 6000000, section="194Q", bill_date="2026-09-11")
	check("TDS 194Q: only the excess over 50L", r4["applicable"] and r4["tds_base"] == 1000000.0,
	      f"base={r4['tds_base']} tds={r4['tds_amount']}")

	# 8. GSTIN -> PAN derivation
	sdoc = frappe.get_doc("Supplier", sup_name)
	sdoc.custom_gstin = "24AADFF3677P1ZY"
	from fountainhead.bill_ocr import install
	install.derive_pan_from_gstin(sdoc)
	check("GSTIN->PAN derived", sdoc.custom_pan == "AADFF3677P", sdoc.custom_pan)
	bad = False
	try:
	    sdoc.custom_gstin = "BADGSTIN123"
	    install.derive_pan_from_gstin(sdoc)
	except Exception:
	    bad = True
	check("bad GSTIN rejected", bad)

	# 9. E-Net row shape
	from fountainhead.bill_ocr import payments
	fake_pi = frappe._dict(outstanding_amount=11850, grand_total=11850)
	fake_sup = frappe._dict(name="SHIV SHAKTI IT SHOPPE", supplier_name="Shiv Shakti IT Shoppe",
	                        custom_ifsc="HDFC0000388", custom_beneficiary_code="SC4012",
	                        custom_bank_account_no="001161900010801", custom_bank_name="HDFC Bank",
	                        custom_bank_branch="Surat", custom_payment_email="x@y.com")
	row = payments._row_for(fake_pi, fake_sup)
	check("E-Net row: 28 columns", len(row) == 28, f"{len(row)} cols")
	check("E-Net row: HDFC -> I", row[0] == "I")
	fake_sup.custom_ifsc = "YESB0000011"
	check("E-Net row: non-HDFC -> N", payments._row_for(fake_pi, fake_sup)[0] == "N")

	# 10. JV duplicate helper importable + academic year helper safe
	check("_je_with_reference callable", api._je_with_reference("X", "Y") == [])
	check("_active_academic_year safe", api._active_academic_year() is None or isinstance(api._active_academic_year(), str))

	# 11. stamp-vs-total cross-check (16 Sept — the Mayur Mandap ૪૬૩ case)
	p5 = {"totals": {"grand_total": 24000.0},
	      "approval_marks": {"stamps": ["E-NET Ref. No. 21,000/- Amt. 20,180/- Date 22.04.2026 Bill No."]}}
	api._stamp_total_check(p5)
	check("stamp mismatch -> warning", any("21,000" in n or "21000" in n for n in p5.get("notes", [])),
	      (p5.get("notes") or [""])[0][:80])
	p6 = {"totals": {"grand_total": 21000.0},
	      "approval_marks": {"stamps": ["E-NET Ref. No. 21,000/- Amt. 20,180/- Date 22.04.2026"]}}
	api._stamp_total_check(p6)
	check("stamp agrees -> silent", not p6.get("notes"))
	p7 = {"totals": {"grand_total": 5000.0},
	      "approval_marks": {"stamps": ["Received on 07-08-2026", "FOUNTAINHEAD SCHOOL"]}}
	api._stamp_total_check(p7)
	check("date-only stamp -> no false amount", not p7.get("notes"))

	# 12. footer-note demotion (16 Sept — the Bharat Lace 1598 case)
	p8 = {"items": [
	    {"description": "Woolen thread", "description_en": "Woolen thread", "quantity": 180, "rate": 10, "amount": 1800},
	    {"description": "Grade 1 to 8, All material used for coactive material",
	     "description_en": "Grade 1 to 8, All material used for creative material",
	     "quantity": 1, "rate": 0, "amount": 0},
	    {"description": "F/PR-3906", "description_en": "F/PR-3906", "quantity": 1, "rate": 0, "amount": 0},
	    {"description": "Sample copy", "description_en": "Sample copy", "quantity": 2, "rate": 0, "amount": 0},
	]}
	api._demote_note_lines(p8)
	check("note lines demoted (4 -> 2 items)", len(p8["items"]) == 2, f"{len(p8['items'])} items")
	check("demoted text kept as notes", sum("not an item line" in n for n in p8.get("notes", [])) == 2)
	check("free-sample line (qty 2, rate 0) kept",
	      any(i.get("description") == "Sample copy" for i in p8["items"]))

	# 13. prompt hardening present
	from fountainhead.bill_ocr import prompt
	check("prompt: bill-date-not-from-stamps rule", "NEVER take it from a rubber stamp" in prompt.USER_PROMPT)
	check("prompt: no-arithmetic-fitting rule", "NEVER adjust one figure" in prompt.USER_PROMPT)
	check("prompt: footer notes excluded from lines", "are NOT lines" in prompt.USER_PROMPT)

	# 14. handwritten corrected date wins (16 Sept — Chetan sir's Metro GT/166 rule)
	from fountainhead.bill_ocr import normalize as nrm
	d1, n1 = nrm.normalize({"invoiceDate": "30/06/2026", "correctedDateHandwritten": "22/07/2026"})
	check("corrected date wins (30/06 -> 22/07)", d1.get("invoiceDate") == "2026-07-22", d1.get("invoiceDate"))
	check("printed date kept for audit", d1.get("printed_invoice_date") == "2026-06-30")
	check("correction note present", any("corrected by hand" in n for n in n1))
	d2, _ = nrm.normalize({"invoiceDate": "30/06/2026"})
	check("no correction -> printed date stands", d2.get("invoiceDate") == "2026-06-30")

	# 15. supplier re-match at serve time (16 Sept — supplier created after read).
	# Site-agnostic: any existing supplier stands in for one created after the
	# bill was read — the suite must stay green on fh AND protego.
	existing_sup = frappe.get_all("Supplier", limit_page_length=1, pluck="name")
	if existing_sup:
	    p9 = {"supplier": {"supplier": None, "candidates": []},
	          "vendor_name_on_bill": existing_sup[0], "vendor_name_english": existing_sup[0],
	          "fields": {}}
	    api._refresh_supplier_match(p9)
	    check("cached reading re-matches a now-existing supplier",
	          p9["fields"].get("supplier") == existing_sup[0],
	          str(p9["supplier"].get("supplier")))

	# 16. item-group grid columns (16 Sept — mixed-bill readability, Ankit Patel)
	for dt in ("Purchase Receipt Item", "Purchase Invoice Item"):
	    check(f"{dt}.item_group in grid",
	          frappe.db.exists("Property Setter", {"doc_type": dt, "field_name": "item_group",
	                                               "property": "in_list_view", "value": "1"}))

	# 17. item-group creation without leaving the form
	g = api.create_item_group_from_bill("_SELFTEST GROUP", None)
	check("create_item_group_from_bill", g.get("created") and g.get("item_group") == "_SELFTEST GROUP")
	g2 = api.create_item_group_from_bill("_SELFTEST GROUP", None)
	check("existing group -> selected, not duplicated", g2.get("existed"))

	# cleanup test vendor fields (leave the vendor; harmless on a dev site)
	frappe.db.rollback()
	print()
	print(f"{'ALL CHECKS PASSED' if all(ok) else 'SOME CHECKS FAILED'} ({sum(ok)}/{len(ok)})")
