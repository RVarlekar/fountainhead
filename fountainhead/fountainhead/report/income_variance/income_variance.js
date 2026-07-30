// Copyright (c) 2025, GreyCube Technologies and contributors
// For license information, please see license.txt

const company = frappe.defaults.get_user_defaults("Company")[0]
frappe.db.get_value('Company', company, 'default_income_account')
	.then(r => {
		let values = r.message
		frappe.query_report.set_filter_value('income_account', values['default_income_account'])
	})

frappe.query_reports["Income Variance"] = {
	"filters": [
		{
			'fieldname': 'fiscal_year',
			'fieldtype': 'Link',
			'label': __('Fiscal Year'),
			'options': 'Fiscal Year',
			'reqd': 1,
			'default' : erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[0]
		},
		{
			'fieldname': 'income_account',
			'fieldtype': 'Link',
			'label': __('Income Account'),
			'options': 'Account',
			'reqd': 1,
			'get_query': () => {
				return {
					filters: {
						'account_type': 'Income Account'
					}
				}
			}
		},
		{
			'fieldname': 'company',
			'fieldtype': 'Link',
			'label': __('Company'),
			'options': 'Company',
			'default': frappe.defaults.get_user_defaults("Company")[0],
		},
		{
			'fieldname': 'grade',
			'fieldtype': 'Link',
			'label': __('Grade'),
			'options': 'FHS Grade',
		}
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data.no_of_students == null) {
			value = value.bold()
		}
		return value;
	},

	// onload: function () {
	// 	console.log("---")
	// 	const company = frappe.defaults.get_user_defaults("Company")[0]
	// 	frappe.db.get_value('Company', company, 'default_income_account')
	// 		.then(r => {
	// 			let values = r.message
	// 			console.log(values)
	// 			frappe.query_report.set_filter_value({
	// 				'income_account': values['default_income_account']
	// 			})
	// 			console.log(values['default_income_account'])
	// 		})
	// }
};
