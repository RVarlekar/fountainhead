"""One-shot: the validated Canteen Expense item-group tree on protego.localhost.

Source: M16 (16 Sept, Bhavik Nayak) validating Krunal sir's budget breakup —
Fuel renamed to Gas; Water/Sanitary/Crockery/Goods/Other Cost added; HR cost
stays OUTSIDE canteen expense. Idempotent: existing groups are kept, only
re-parented under Canteen Expense when they sit at the root.

Run: bench --site protego.localhost execute fountainhead.bill_ocr.setup_kitchen_groups.run
"""

PARENT = "Canteen Expense"
CHILDREN = [
	"Milk & Dairy",
	"Grains",
	"Grocery",
	"Cooking Oil",
	"Gas",
	"Fruits & Vegetables",
	"Water",
	"Sanitary",
	"Crockery",
	"Goods",
	"Other Cost",
]


def run():
	import frappe

	root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name") or "All Item Groups"

	if not frappe.db.exists("Item Group", PARENT):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": PARENT,
		                "parent_item_group": root, "is_group": 1}).insert(ignore_permissions=True)
		print(f"created parent: {PARENT}")
	else:
		if not frappe.db.get_value("Item Group", PARENT, "is_group"):
			frappe.db.set_value("Item Group", PARENT, "is_group", 1)
			print(f"{PARENT}: marked as group")
		print(f"parent exists: {PARENT}")

	for name in CHILDREN:
		if frappe.db.exists("Item Group", name):
			doc = frappe.get_doc("Item Group", name)
			changed = []
			# A sub-group that itself has children (e.g. Grocery got a sub-head
			# during the UAT sitting) must be a group node, or NestedSet refuses.
			if frappe.db.exists("Item Group", {"parent_item_group": name}) and not doc.is_group:
				doc.is_group = 1
				changed.append("is_group=1")
			if doc.parent_item_group != PARENT:
				changed.append(f"parent {doc.parent_item_group} -> {PARENT}")
				doc.parent_item_group = PARENT
			if changed:
				doc.save(ignore_permissions=True)
				print(f"updated: {name} ({', '.join(changed)})")
			else:
				print(f"ok: {name}")
		else:
			frappe.get_doc({"doctype": "Item Group", "item_group_name": name,
			                "parent_item_group": PARENT, "is_group": 0}).insert(ignore_permissions=True)
			print(f"created: {name}")

	frappe.db.commit()
	from frappe.utils.nestedset import rebuild_tree
	rebuild_tree("Item Group")
	frappe.db.commit()

	kids = frappe.get_all("Item Group", filters={"parent_item_group": PARENT},
	                      order_by="name", pluck="name")
	print(f"\n{PARENT} now has {len(kids)} sub-groups: {', '.join(kids)}")
	print("TREE-DONE")
