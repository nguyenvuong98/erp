import frappe

def run():
    # Tạo root nếu chưa có
    if not frappe.db.exists("Item Group", "All Item Groups"):
        root = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "All Item Groups",
            "is_group": 1,
            "parent_item_group": None
        })
        root.insert(ignore_permissions=True)
        print("Đã tạo root Item Group: All Item Groups")

    # Lấy dữ liệu từ bảng Groups
    groups = frappe.db.sql("SELECT groupname FROM `Groups`", as_dict=True)

    for g in groups:
        groupname = g["groupname"]

        if frappe.db.exists("Item Group", groupname):
            print(f"Skipped {groupname} (đã tồn tại)")
            continue

        doc = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": groupname,
            "parent_item_group": "All Item Groups",
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        print(f"Đã tạo Item Group: {groupname}")

    frappe.db.commit()

