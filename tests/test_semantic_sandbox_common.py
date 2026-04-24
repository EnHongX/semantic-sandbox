import unittest

from semantic_sandbox_common import parse_upload_rows


class ParseUploadRowsTests(unittest.TestCase):
    def test_csv_with_utf8_bom_uses_text_header(self) -> None:
        content = "\ufefftext,category\nhello,tech\n".encode("utf-8")

        rows = parse_upload_rows(content, "sample.csv")

        self.assertEqual(rows, [{"text": "hello", "category": "tech"}])

    def test_json_with_utf8_bom_is_supported(self) -> None:
        content = '\ufeff[{"text":"hello"}]'.encode("utf-8")

        rows = parse_upload_rows(content, "sample.json")

        self.assertEqual(rows, [{"text": "hello"}])


if __name__ == "__main__":
    unittest.main()
