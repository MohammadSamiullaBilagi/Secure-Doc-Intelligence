from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

def generate_dirty_invoice(file_name: str):
    c = canvas.Canvas(file_name, pagesize=letter)
    width, height = letter

    # --- Header ---
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "TAX INVOICE")
    
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, "Invoice Number: INV-2026-001")
    c.drawString(50, height - 85, "Date: February 15, 2026")

    # --- Vendor Details (TRIGGER: Invalid GSTIN - only 10 chars) ---
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, height - 120, "Vendor: Global Catering Services")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 135, "Address: 123 Industrial Area, Bangalore")
    c.drawString(50, height - 150, "GSTIN: 29ABCDE123") # VIOLATION: Too short

    # --- Purchaser Details (TRIGGER: Invalid GSTIN) ---
    c.drawString(350, height - 120, "Bill To: TechSolutions Pvt Ltd")
    c.drawString(350, height - 135, "Address: 456 IT Park, Dharwad")
    c.drawString(350, height - 150, "GSTIN: 29XXXXX000") # VIOLATION: Too short

    # --- Table Header ---
    c.line(50, height - 170, 550, height - 170)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, height - 185, "Description")
    c.drawString(400, height - 185, "Amount (INR)")
    c.line(50, height - 195, 550, height - 195)

    # --- Line Items (TRIGGER: Blocked Credit - Outdoor Catering) ---
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 215, "1. Annual Day Outdoor Catering Services") # VIOLATION: Sec 17(5)
    c.drawString(400, height - 215, "75,000.00")
    
    c.drawString(50, height - 235, "2. Event Management Fees")
    c.drawString(400, height - 235, "25,000.00")

    # --- Totals ---
    c.line(350, height - 250, 550, height - 250)
    c.drawString(350, height - 265, "Total Taxable Value:")
    c.drawString(480, height - 265, "1,00,000.00")
    c.drawString(350, height - 280, "GST (18%):")
    c.drawString(480, height - 280, "18,000.00")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(350, height - 295, "Grand Total:")
    c.drawString(480, height - 295, "1,18,000.00")

    # --- Payment Terms (TRIGGER: MSME Violation - 90 days) ---
    c.setFont("Helvetica-Bold", 11)
    c.setStrokeColor(colors.red)
    c.drawString(50, height - 350, "PAYMENT TERMS:")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 365, "Payment must be made within 90 days of invoice date.") # VIOLATION: Exceeds 45 days

    # --- Compliance Note (TRIGGER: Missing E-Invoice QR/IRN) ---
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 50, "Note: E-invoice IRN and QR code generation is currently under maintenance.") # Explicit missing IRN

    c.save()
    print(f"Successfully generated {file_name}")

if __name__ == "__main__":
    generate_dirty_invoice("test_invoice_dirty.pdf")