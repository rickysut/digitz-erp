// Copyright (c) 2024, Techxcel Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Leave Period", {
    onload(frm) {
      assign_defaults(frm);
      },
    from_date: (frm)=>{
          if (frm.doc.from_date && !frm.doc.to_date) {
              var a_year_from_start = frappe.datetime.add_months(frm.doc.from_date, 12);
              frm.set_value("to_date", frappe.datetime.add_days(a_year_from_start, -1));
          }
      },
  });
  
  function assign_defaults(frm)
  {
      if(frm.is_new())
      {
          
      }
   }
  