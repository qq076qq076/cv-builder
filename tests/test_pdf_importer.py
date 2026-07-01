import unittest

from app.importers.pdf import can_extract_pdf, extract_text_from_pdf_bytes


SIMPLE_TEXT_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length 44 >> stream
BT /F1 24 Tf 100 700 Td (Hello PDF Resume) Tj ET
endstream endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000311 00000 n 
trailer << /Root 1 0 R /Size 6 >>
startxref
405
%%EOF"""


class PdfImporterTest(unittest.TestCase):
    def test_can_extract_pdf_by_extension_or_content_type(self) -> None:
        self.assertTrue(can_extract_pdf("resume.pdf", None))
        self.assertTrue(can_extract_pdf("resume.bin", "application/pdf"))
        self.assertFalse(can_extract_pdf("resume.txt", "text/plain"))

    def test_extract_text_from_pdf_bytes(self) -> None:
        self.assertIn("Hello PDF Resume", extract_text_from_pdf_bytes(SIMPLE_TEXT_PDF))


if __name__ == "__main__":
    unittest.main()

