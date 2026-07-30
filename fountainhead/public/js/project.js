frappe.ui.form.on("Project",{
    setup : function(frm) {
        console.log("setup");
        frm.set_query("budget_area_item_group","custom_project",function(doc, cdt, cdn) {
            return {
                filters : {
                    // "is_group": 1,
                    "parent_item_group": ["!=",""]
                }
            }
        })
    },

    refresh(frm) {
        $(`div[data-label="View"]`).find(`button.btn-default.ellipsis`).css({'background-color':'#87CEFA','font-weight': 'bold','color':'#fff'})
        if (frm.is_new() == undefined) {
            frm.add_custom_button(__('Project Budget Report'), () => show_project_budget_report_from_project(frm),__("View"))
            .css({'background-color':'#87CEFA','font-weight': 'bold','color':'#fff'});
        }
    },
})

frappe.ui.form.on("Project Details",{
    budget_area_in_sqft: function(frm, cdt, cdn) {
        calculate_budget_amount(frm, cdt, cdn)
    },

    budget_area_rate_per_area: function(frm, cdt, cdn) {
        calculate_budget_amount(frm, cdt, cdn)
    }
})

let calculate_budget_amount = function(frm, cdt, cdn) {
    var row = locals[cdt][cdn]
    let budget_amount = row.budget_area_in_sqft * row.budget_area_rate_per_area
    frappe.model.set_value(cdt, cdn, "budget_amount", budget_amount)
}

function show_project_budget_report_from_project(frm) {
    frappe.open_in_new_tab = true;
    frappe.route_options = {
        project: frm.doc.name,
    };                    
    frappe.set_route("query-report", "Project Budget");
}