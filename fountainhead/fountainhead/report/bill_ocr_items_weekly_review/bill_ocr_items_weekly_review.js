// Weekly worklist of items created from bill scans. Review = open the item,
// tick "Reviewed" in its Bill OCR section; the row leaves the pending view.

frappe.query_reports["Bill OCR Items - Weekly Review"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Show"),
			fieldtype: "Select",
			options: ["Pending review", "Reviewed", "All"],
			default: "Pending review",
		},
		{
			fieldname: "from_date",
			label: __("Created on or after"),
			fieldtype: "Date",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "similar" && data && data.similar) {
			value = `<span style="color:var(--red-500)">${value}</span>`;
		}
		if (column.fieldname === "times_used" && data && !data.times_used) {
			value = `<span style="color:var(--orange-500);font-weight:600">0 — never purchased</span>`;
		}
		return value;
	},
};
