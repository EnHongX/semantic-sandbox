import os
import tempfile
import unittest
from pathlib import Path

import semantic_sandbox_common as common


class LoggingHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = {"METADATA_STORE": os.environ.get("METADATA_STORE")}
        os.environ["METADATA_STORE"] = "json"
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._old_paths = {
            "AUDIT_LOG_FILE": common.AUDIT_LOG_FILE,
            "SEARCH_LOG_FILE": common.SEARCH_LOG_FILE,
            "ERROR_LOG_FILE": common.ERROR_LOG_FILE,
        }
        common.AUDIT_LOG_FILE = base / "audit.jsonl"
        common.SEARCH_LOG_FILE = base / "search.jsonl"
        common.ERROR_LOG_FILE = base / "errors.jsonl"

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in self._old_paths.items():
            setattr(common, key, value)
        self._tmp.cleanup()

    def test_audit_logs_are_listed_without_sensitive_payload(self) -> None:
        common.append_audit_log({
            "event": "web_login_failed",
            "level": "warning",
            "actor": "web:admin",
            "backend": "qdrant",
            "method": "POST",
            "path": "/login",
            "metadata": {"username": "admin"},
        })

        rows = common.list_audit_logs(backend="qdrant")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "web_login_failed")
        self.assertEqual(rows[0]["metadata"], {"username": "admin"})
        self.assertNotIn("password", rows[0]["metadata"])

    def test_search_and_error_logs_have_list_views(self) -> None:
        common.append_search_log({"backend": "qdrant", "query": "hello", "result_count": 1})
        common.append_error_log({"backend": "qdrant", "operation": "search", "surface": "unit", "error": "boom"})

        searches = common.list_search_logs(backend="qdrant")
        errors = common.list_error_logs(backend="qdrant")

        self.assertEqual(searches[0]["query"], "hello")
        self.assertEqual(errors[0]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
