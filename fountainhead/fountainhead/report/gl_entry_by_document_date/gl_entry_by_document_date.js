// Filters for "GL Entry by Document Date". The from/to dates apply to the
// DOCUMENT date by default — the whole point of the report.

frappe.query_reports["GL Entry by Document Date"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "date_basis",
			label: __("Dates mean"),
			fieldtype: "Select",
			options: ["Document Date", "Posting Date"],
			default: "Document Date",
		},
		{
			fieldname: "voucher_type",
			label: __("Voucher Type"),
			fieldtype: "Select",
			options: ["", "Purchase Invoice", "Journal Entry", "Payment Entry", "Purchase Receipt", "Sales Invoice"],
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: () => ({ filters: { is_group: 0 } }),
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Data",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_late" && data && data.days_late > 30) {
			value = `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
