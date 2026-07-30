// Copyright (c) 2025, GreyCube Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Income & Expense Budget Vs Actual"] = {
	"filters": [
		{
			fieldname: "company",
			fieldtype: "Link",
			label: "Company",
			options: "Company",
			default: frappe.user_defaults.company,
		},
		{
			fieldname: "fiscal_year",
			fieldtype: "Link",
			label: "Fiscal Year",
			options: "Fiscal Year",
			reqd: 1,
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[0]
		},
		{
			fieldname: "show_zero_values",
			fieldtype: "Check",
			label: "Show Zero Values",
			default: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.indent == 0 || ["'Total Income (Credit)'", "'Total Expense (Debit)'", "'Profit for the year'"].includes(data.account)) {
			value = value.bold();
		}
		if (data.warn_if_negative && data[column.fieldname] < 0) {
			value = `<span class="text-danger">${value}</span>`
		}
		if (data.warn_if_negative && data[column.fieldname] > 0) {
			value = `<span class="text-success">${value}</span>`
		}
		return value;
	},
};
