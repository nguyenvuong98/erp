import frappe

@frappe.whitelist()
def search_customers_by_staff(keyword=""):
	"""
	Tìm kiếm khách hàng theo keyword và lọc theo nhân viên phụ trách
	Chỉ trả về khách hàng mà user hiện tại đang phụ trách
	"""
	from frappe import _
	
	# Lấy user hiện tại
	current_user = frappe.session.user
	
	# Nếu là Administrator thì không lọc
	if current_user == "Administrator":
		filters = []
	else:
		# Lọc theo nhân viên phụ trách
		filters = [
			["custom_staffinchargeid", "=", current_user]
		]
	
	# Thêm điều kiện tìm kiếm theo keyword nếu có
	if keyword:
		filters.append(["customer_name", "like", f"%{keyword}%"])
	
	# Lấy danh sách khách hàng
	customers = frappe.get_all(
		"Customer",
		filters=filters,
		fields=["name", "customer_name", "mobile_no", "email_id", "custom_staffinchargeid"],
		limit=20,
		order_by="customer_name asc"
	)
	
	return customers