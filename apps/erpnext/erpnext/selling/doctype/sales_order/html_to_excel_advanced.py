import frappe
from io import BytesIO
import xlsxwriter
from bs4 import BeautifulSoup
import re

@frappe.whitelist()
def convert_html_to_excel_sales_order(doctype, docname, print_format=None):
    """
    Chuyển đổi HTML Print Format sang Excel với định dạng đẹp
    """
    try:
        # Get document
        sales_order = frappe.get_doc("Sales Order", docname)
        
        # Get related docs with error handling
        customer_info = None
        company_info = None
        warehouse_info = None
        
        try:
            if sales_order.customer:
                customer_info = frappe.get_doc("Customer", sales_order.customer)
        except Exception as e:
            frappe.log_error(f"Error loading customer: {str(e)}", "Excel Export")
        
        try:
            if sales_order.company:
                company_info = frappe.get_doc("Company", sales_order.company)
        except Exception as e:
            frappe.log_error(f"Error loading company: {str(e)}", "Excel Export")
        
        try:
            if sales_order.set_warehouse:
                warehouse_info = frappe.get_doc("Warehouse", sales_order.set_warehouse)
        except Exception as e:
            frappe.log_error(f"Error loading warehouse: {str(e)}", "Excel Export")
        
        # Check if this is a download request
        is_download = frappe.local.request.args.get('download') == '1'
        
        if not is_download:
            # First call - just return success to avoid CORS issues
            return {
                "message": "Excel file is ready",
                "status": "success"
            }
        
        # Create Excel file
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(docname[:31])
        
        # Hide gridlines
        worksheet.hide_gridlines(2)
        
        # Định dạng styles
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter'
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 8,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#f0f0f0'
        })
        
        cell_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        text_left_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        number_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'num_format': '#,##0',
            'align': 'right',
            'valign': 'vcenter'
        })
        
        # Set column widths to match the image (after removing QC and T/Lẻ)
        worksheet.set_column('A:A', 4)   # STT
        worksheet.set_column('B:B', 9)   # Mã vật tư
        worksheet.set_column('C:C', 35)  # Tên vật tư
        worksheet.set_column('D:D', 5)   # ĐVT
        worksheet.set_column('E:E', 10)  # Đơn giá
        worksheet.set_column('F:F', 5)   # SL
        worksheet.set_column('G:G', 5)   # %CK
        worksheet.set_column('H:H', 10)  # Chiết khấu
        worksheet.set_column('I:I', 12)  # Thành tiền
        
        bold_format = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        info_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        right_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter'
        })
        
        # Format for signature section (no border)
        signature_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'bold': True
        })
        
        hint_format = workbook.add_format({
            'font_size': 9,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'italic': True
        })
        
        row = 0
        
        # Company header - left side
        worksheet.write(row, 0, "CÔNG TY CỔ PHẦN THƯƠNG MẠI XNK SỨC SỐNG MỚI", bold_format)
        # Right side info
        current_datetime = frappe.utils.now_datetime()
        date_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")
        worksheet.write(row, 6, f"Ngày in: {date_str}", right_format)
        row += 1
        
        worksheet.write(row, 0, "LK14-04 KĐT Thanh Hà - Xã Cự Khê - H. Thanh Oai - Hà Nội", info_format)
        worksheet.write(row, 6, f"Người in: {frappe.session.user}", right_format)
        row += 1
        
        # issued_by = getattr(sales_order, 'custom_issued_by', None) or frappe.session.user
        # worksheet.write(row, 6, f"Người xuất: {issued_by}", right_format)
        # row += 1
        
        # Warehouse info
        # warehouse_code = warehouse_info.warehouse_code if warehouse_info and hasattr(warehouse_info, 'warehouse_code') else "00"
        # warehouse_name = warehouse_info.warehouse_name if warehouse_info and hasattr(warehouse_info, 'warehouse_name') else sales_order.set_warehouse or "Kho Tổng"
        worksheet.write(row, 0, f"{sales_order.set_warehouse}", info_format)
        
        employee_code = ''
        employee_name =  ''
        # worksheet.write(row, 6, f"Nhân viên: {employee_code} - {employee_name}", right_format)
        row += 2
        
        # Title
        worksheet.merge_range(row, 0, row, 8, "PHIẾU XUẤT KHO", title_format)
        worksheet.set_row(row, 30)
        row += 2
        
        # Info section - left column
        # worksheet.write(row, 0, f"Số phiếu:", bold_format)
        worksheet.merge_range(row, 0, row, 1, f"Số phiếu:", bold_format)
        worksheet.merge_range(row, 2, row, 3, sales_order.name, info_format)
        # Info section - right column
        customer_code = sales_order.custom_end_customer
        # customer_id = getattr(sales_order, 'custom_customer_id', None) or sales_order.customer_id
        worksheet.write(row, 4, "Khách hàng:", bold_format)
        worksheet.merge_range(row, 4, row, 5, "Khách hàng:", bold_format)
        # worksheet.merge_range(row, 6, row, 10, customer_info.custom_id+"-"+customer_code, info_format)
        worksheet.merge_range(row, 6, row, 10, customer_code, info_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 1, "Ngày giao dịch:", bold_format)
        date_str = frappe.utils.formatdate(sales_order.transaction_date, "dd/MM/yyyy") if sales_order.transaction_date else ""
        worksheet.merge_range(row, 2, row, 3, date_str, info_format)
        worksheet.merge_range(row, 4, row, 5, "Địa chỉ:", bold_format)
        
        customer_address = ""
        if customer_info and hasattr(customer_info, 'custom_address'):
            customer_address = customer_info.custom_address or ""
        worksheet.merge_range(row, 6, row, 10, customer_address, info_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 1, "Kho xuất:", bold_format)
        # warehouse_code_display = getattr(warehouse_info, 'warehouse_code', None) if warehouse_info else '00003'
        warehouse_display = f"{sales_order.set_warehouse or ''}"
        worksheet.merge_range(row, 2, row, 3, warehouse_display, info_format)
        worksheet.merge_range(row, 4, row, 5, "Điện thoại:", bold_format)
        
        mobile = ""
        if customer_info:
            if hasattr(customer_info, 'custom_telephone'):
                mobile = customer_info.custom_telephone or ""
            elif hasattr(customer_info, 'custom_mobile'):
                mobile = customer_info.custom_mobile or ""
        worksheet.merge_range(row, 6, row, 10, mobile, info_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 1, "Diễn giải:", bold_format)
        worksheet.merge_range(row, 2, row, 3, "", info_format)
        row += 2
        
        # Table headers
        headers = [
            "STT", "Mã vật tư", "Tên vật tư", "ĐVT",
            "Đơn giá", "SL", "%CK", "Chiết khấu", "Thành tiền"
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1
        
        # Table data
        total_qty = 0
        total_amount = 0
        
        for idx, item in enumerate(sales_order.items, 1):
            worksheet.write(row, 0, idx, cell_format)
            worksheet.write(row, 1, item.item_code, cell_format)
            worksheet.write(row, 2, item.item_name or item.item_code, text_left_format)
            worksheet.write(row, 3, item.stock_uom or item.uom, cell_format)
            worksheet.write(row, 4, item.rate or 0, number_format)
            worksheet.write(row, 5, item.delivered_qty or item.qty or 0, cell_format)
            worksheet.write(row, 6, item.custom_p_discount or 0, number_format)
            discount = float(item.custom_p_discount or 0) * (item.amount or 0) / 100
            worksheet.write(row, 7, discount, number_format)
            worksheet.write(row, 8, item.amount or 0, number_format)
            
            total_qty += item.qty or 0
            total_amount += item.amount or 0
            
            row += 1
        
        # Fill empty rows if needed
        if len(sales_order.items) < 5:
            for i in range(5 - len(sales_order.items)):
                worksheet.write(row, 0, len(sales_order.items) + i + 1, cell_format)
                for col in range(1, 9):
                    worksheet.write(row, col, "", cell_format)
                row += 1
        
        # Totals
        bold_cell_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'bold': True
        })
        
        worksheet.merge_range(row, 0, row, 4, "Tổng tiền hàng", bold_cell_format)
        worksheet.write(row, 5, total_qty, bold_cell_format)
        worksheet.write(row, 6, "", bold_cell_format)
        total_discount = getattr(sales_order, 'discount_amount', None) or 0
        worksheet.write(row, 7, total_discount, number_format)
        worksheet.write(row, 8, total_amount, number_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 7, "Tiền CK", bold_cell_format)
        worksheet.write(row, 8, sales_order.discount_amount or 0, number_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 7, "Tổng thanh toán", bold_cell_format)
        worksheet.write(row, 8, sales_order.grand_total or 0, number_format)
        row += 2
        
        # Amount in words
        in_words = getattr(sales_order, 'custom_in_words_viet_nam', None) or ''
        worksheet.merge_range(row, 0, row, 8, f"Tổng tiền bằng chữ: {in_words}", bold_format)
        row += 2
        
        # Date section (right aligned)
        date_str = f"Ngày .......tháng......năm......."
        if sales_order.transaction_date:
            date_str = f"Ngày {frappe.utils.formatdate(sales_order.transaction_date, 'dd')}, tháng {frappe.utils.formatdate(sales_order.transaction_date, 'MM')}, năm {frappe.utils.formatdate(sales_order.transaction_date, 'yyyy')}"
        worksheet.merge_range(row, 6, row, 8, date_str, right_format)
        row += 2
        
        # Signatures - 4 columns layout (no border)
        signs = ["Người giao hàng", "Người nhận hàng", "Thủ kho", "Người lập phiếu"]
        col_positions = [0, 2, 4, 6]  # Starting column for each signature
        
        for i, sign in enumerate(signs):
            col = col_positions[i]
            if i < 3:  # First 3 signatures span 2 columns
                worksheet.merge_range(row, col, row, col + 1, sign, signature_format)
                worksheet.merge_range(row + 1, col, row + 1, col + 1, "(Ký, họ tên)", hint_format)
            else:  # Last signature spans remaining columns
                worksheet.merge_range(row, col, row, 8, sign, signature_format)
                worksheet.merge_range(row + 1, col, row + 1, 8, "(Ký, họ tên)", hint_format)
        
        # Set page setup for printing
        worksheet.set_portrait()
        worksheet.set_paper(9)  # A4 paper
        worksheet.set_print_scale(100)
        worksheet.center_horizontally()
        
        workbook.close()
        output.seek(0)
        
        # Return file for download
        frappe.local.response.filename = f'PhieuXuatKho-{docname}.xlsx'
        frappe.local.response.filecontent = output.getvalue()
        frappe.local.response.type = 'download'
        
    except Exception as e:
        frappe.log_error(f"Error in convert_html_to_excel: {str(e)}\n{frappe.get_traceback()}", "Excel Export Error")
        frappe.throw(f"Lỗi khi xuất file Excel: {str(e)}")

@frappe.whitelist()
def convert_html_to_excel_delivery_note(doctype, docname, print_format=None):
    """
    Chuyển đổi Delivery Note sang Excel với định dạng đẹp
    """
    try:
        # Get document
        delivery_note = frappe.get_doc("Delivery Note", docname)
        
        # Get related docs with error handling
        customer_info = None
        company_info = None
        warehouse_info = None
        
        try:
            if delivery_note.customer:
                customer_info = frappe.get_doc("Customer", delivery_note.custom_end_customer)
        except Exception as e:
            frappe.log_error(f"Error loading customer: {str(e)}", "Excel Export")
        
        try:
            if delivery_note.company:
                company_info = frappe.get_doc("Company", delivery_note.company)
        except Exception as e:
            frappe.log_error(f"Error loading company: {str(e)}", "Excel Export")
        
        try:
            if delivery_note.set_warehouse:
                warehouse_info = frappe.get_doc("Warehouse", delivery_note.set_warehouse)
        except Exception as e:
            frappe.log_error(f"Error loading warehouse: {str(e)}", "Excel Export")
        
        # Check if this is a download request
        is_download = frappe.local.request.args.get('download') == '1'
        
        if not is_download:
            # First call - just return success to avoid CORS issues
            return {
                "message": "Excel file is ready",
                "status": "success"
            }
        
        # Create Excel file
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(docname[:31])
        
        # Hide gridlines
        worksheet.hide_gridlines(2)
        
        # Định dạng styles
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter'
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 8,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#f0f0f0'
        })
        
        cell_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        text_left_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        number_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'num_format': '#,##0',
            'align': 'right',
            'valign': 'vcenter'
        })
        
        # Set column widths
        worksheet.set_column('A:A', 4)   # STT
        worksheet.set_column('B:B', 9)   # Mã vật tư
        worksheet.set_column('C:C', 35)  # Tên vật tư
        worksheet.set_column('D:D', 5)   # ĐVT
        worksheet.set_column('E:E', 10)  # Đơn giá
        worksheet.set_column('F:F', 5)   # SL
        worksheet.set_column('G:G', 5)   # %CK
        worksheet.set_column('H:H', 10)  # Chiết khấu
        worksheet.set_column('I:I', 12)  # Thành tiền
        
        bold_format = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        info_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        right_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter'
        })
        
        signature_format = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'bold': True
        })
        
        hint_format = workbook.add_format({
            'font_size': 9,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'italic': True
        })
        
        row = 0
        
        # Company header - left side
        worksheet.write(row, 0, "CÔNG TY CỔ PHẦN THƯƠNG MẠI XNK SỨC SỐNG MỚI", bold_format)
        # Right side info
        current_datetime = frappe.utils.now_datetime()
        date_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")
        worksheet.write(row, 6, f"Ngày in: {date_str}", right_format)
        row += 1
        
        worksheet.write(row, 0, "LK14-04 KĐT Thanh Hà - Xã Cự Khê - H. Thanh Oai - Hà Nội", info_format)
        worksheet.write(row, 6, f"Người in: {frappe.session.user}", right_format)
        row += 1
        
        worksheet.write(row, 0, f"{delivery_note.set_warehouse}", info_format)
        row += 2
        
        # Title
        worksheet.merge_range(row, 0, row, 8, "PHIẾU GIAO HÀNG", title_format)
        worksheet.set_row(row, 30)
        row += 2
        
        # Info section - left column
        worksheet.merge_range(row, 0, row, 1, f"Số phiếu:", bold_format)
        worksheet.merge_range(row, 2, row, 3, delivery_note.name, info_format)
        
        # Info section - right column
        customer_code = delivery_note.custom_end_customer
        worksheet.merge_range(row, 4, row, 5, "Khách hàng:", bold_format)
        worksheet.merge_range(row, 6, row, 10, customer_code, info_format)
        row += 1
        
        # Transaction date
        worksheet.merge_range(row, 0, row, 1, "Ngày giao dịch:", bold_format)
        date_str = frappe.utils.formatdate(delivery_note.posting_date, "dd/MM/yyyy") if delivery_note.posting_date else ""
        worksheet.merge_range(row, 2, row, 3, date_str, info_format)
        
        # Customer address
        worksheet.merge_range(row, 4, row, 5, "Địa chỉ:", bold_format)
        customer_address = ""
        if customer_info and hasattr(customer_info, 'custom_address'):
            customer_address = customer_info.custom_address or ""
        worksheet.merge_range(row, 6, row, 10, customer_address, info_format)
        row += 1
        
        # Warehouse info
        worksheet.merge_range(row, 0, row, 1, "Kho xuất:", bold_format)
        warehouse_display = f"{delivery_note.set_warehouse or ''}"
        worksheet.merge_range(row, 2, row, 3, warehouse_display, info_format)
        
        # Phone
        worksheet.merge_range(row, 4, row, 5, "Điện thoại:", bold_format)
        mobile = ""
        if customer_info:
            if hasattr(customer_info, 'custom_telephone'):
                mobile = customer_info.custom_telephone or ""
            elif hasattr(customer_info, 'custom_mobile'):
                mobile = customer_info.custom_mobile or ""
        worksheet.merge_range(row, 6, row, 10, mobile, info_format)
        row += 1
        
        # Notes section
        worksheet.merge_range(row, 0, row, 1, "Diễn giải:", bold_format)
        worksheet.merge_range(row, 2, row, 3, "", info_format)
        row += 2
        
        # Table headers
        headers = [
            "STT", "Mã vật tư", "Tên vật tư", "ĐVT",
            "Đơn giá", "SL", "%CK", "Chiết khấu", "Thành tiền"
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1
        
        # Table data
        total_qty = 0
        total_amount = 0
        
        for idx, item in enumerate(delivery_note.items, 1):
            worksheet.write(row, 0, idx, cell_format)
            worksheet.write(row, 1, item.item_code, cell_format)
            worksheet.write(row, 2, item.item_name or item.item_code, text_left_format)
            worksheet.write(row, 3, item.stock_uom or item.uom, cell_format)
            worksheet.write(row, 4, item.rate or 0, number_format)
            worksheet.write(row, 5, item.qty or 0, cell_format)
            worksheet.write(row, 6, item.custom_p_discount or 0, number_format)
            discount = (item.custom_p_discount or 0) * (item.amount or 0) / 100
            worksheet.write(row, 7, discount, number_format)
            worksheet.write(row, 8, item.amount or 0, number_format)
            
            total_qty += item.qty or 0
            total_amount += item.amount or 0
            
            row += 1
        
        # Fill empty rows if needed
        if len(delivery_note.items) < 5:
            for i in range(5 - len(delivery_note.items)):
                worksheet.write(row, 0, len(delivery_note.items) + i + 1, cell_format)
                for col in range(1, 9):
                    worksheet.write(row, col, "", cell_format)
                row += 1
        
        # Totals
        bold_cell_format = workbook.add_format({
            'font_size': 7,
            'font_name': 'Times New Roman',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'bold': True
        })
        
        worksheet.merge_range(row, 0, row, 4, "Tổng tiền hàng", bold_cell_format)
        worksheet.write(row, 5, total_qty, bold_cell_format)
        worksheet.write(row, 6, "", bold_cell_format)
        total_discount = getattr(delivery_note, 'discount_amount', None) or 0
        worksheet.write(row, 7, total_discount, number_format)
        worksheet.write(row, 8, total_amount, number_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 7, "Tiền CK", bold_cell_format)
        worksheet.write(row, 8, delivery_note.discount_amount or 0, number_format)
        row += 1
        
        worksheet.merge_range(row, 0, row, 7, "Tổng thanh toán", bold_cell_format)
        worksheet.write(row, 8, delivery_note.grand_total or 0, number_format)
        row += 2
        
        # Amount in words
        in_words = getattr(delivery_note, 'custom_in_words_viet_nam', None) or ''
        worksheet.merge_range(row, 0, row, 8, f"Tổng tiền bằng chữ: {in_words}", bold_format)
        row += 2
        
        # Date section
        date_str = f"Ngày .......tháng......năm......."
        if delivery_note.posting_date:
            date_str = f"Ngày {frappe.utils.formatdate(delivery_note.posting_date, 'dd')}, tháng {frappe.utils.formatdate(delivery_note.posting_date, 'MM')}, năm {frappe.utils.formatdate(delivery_note.posting_date, 'yyyy')}"
        worksheet.merge_range(row, 6, row, 8, date_str, right_format)
        row += 2
        
        # Signatures
        signs = ["Người giao hàng", "Người nhận hàng", "Thủ kho", "Người lập phiếu"]
        col_positions = [0, 2, 4, 6]
        
        for i, sign in enumerate(signs):
            col = col_positions[i]
            if i < 3:
                worksheet.merge_range(row, col, row, col + 1, sign, signature_format)
                worksheet.merge_range(row + 1, col, row + 1, col + 1, "(Ký, họ tên)", hint_format)
            else:
                worksheet.merge_range(row, col, row, 8, sign, signature_format)
                worksheet.merge_range(row + 1, col, row + 1, 8, "(Ký, họ tên)", hint_format)
        
        # Page setup
        worksheet.set_portrait()
        worksheet.set_paper(9)  # A4 paper
        worksheet.set_print_scale(100)
        worksheet.center_horizontally()
        
        workbook.close()
        output.seek(0)
        
        # Return file for download
        frappe.local.response.filename = f'PhieuGiaoHang-{docname}.xlsx'
        frappe.local.response.filecontent = output.getvalue()
        frappe.local.response.type = 'download'
        
    except Exception as e:
        frappe.log_error(f"Error in convert_html_to_excel_delivery_note: {str(e)}\n{frappe.get_traceback()}", "Excel Export Error")
        frappe.throw(f"Lỗi khi xuất file Excel: {str(e)}")