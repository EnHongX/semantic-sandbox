import os
import unittest
from pathlib import Path


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_TESTS") == "1" and os.environ.get("DATABASE_URL"),
    "set RUN_POSTGRES_TESTS=1 and DATABASE_URL to run PostgreSQL integration tests",
)
class PostgresStoreIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["METADATA_STORE"] = "postgres"
        os.environ.setdefault("VECTOR_BACKEND", "qdrant")
        from semantic_sandbox_common import clear_documents

        clear_documents()

    def tearDown(self) -> None:
        from semantic_sandbox_common import clear_documents
        from semantic_sandbox_postgres import close_pool

        clear_documents()
        close_pool()

    def test_document_lifecycle_and_import_job(self) -> None:
        from semantic_sandbox_common import (
            add_documents,
            append_audit_log,
            append_error_log,
            append_search_log,
            build_documents_from_texts,
            create_import_job,
            list_audit_logs,
            list_error_logs,
            list_import_jobs,
            list_search_logs,
            list_documents,
            load_import_job,
        )

        records, existing = build_documents_from_texts(
            ["postgres integration", "postgres integration"],
            seed_files=[Path("data/sample_en.json")],
            source="test",
            category="ops",
            tags=["db"],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(existing), 1)

        add_documents(records)

        repeated, repeated_existing = build_documents_from_texts(
            ["postgres integration"],
            seed_files=[Path("data/sample_en.json")],
            source="test",
        )
        self.assertEqual(repeated, [])
        self.assertEqual(len(repeated_existing), 1)

        docs, total = list_documents()
        self.assertEqual(total, 1)
        self.assertEqual(docs[0]["category"], "ops")

        append_search_log({"backend": "qdrant", "query": "postgres", "result_count": 1})
        append_error_log({"backend": "qdrant", "operation": "test", "surface": "unit", "error": "sample"})
        append_audit_log({"backend": "qdrant", "event": "unit_event", "actor": "unit", "metadata": {"ok": True}})
        job = create_import_job(source_filename="sample.csv", inserted=1, existing=[], errors=[])

        self.assertEqual(load_import_job(job["job_id"])["inserted"], 1)
        self.assertEqual(list_search_logs(backend="qdrant")[0]["query"], "postgres")
        self.assertEqual(list_error_logs(backend="qdrant")[0]["error"], "sample")
        self.assertEqual(list_audit_logs(backend="qdrant")[0]["event"], "unit_event")
        self.assertEqual(list_import_jobs()[0]["inserted"], 1)

    def test_pending_document_can_retry_vector_write(self) -> None:
        from semantic_sandbox_common import build_documents_from_texts

        first, first_existing = build_documents_from_texts(
            ["pending retry integration"],
            seed_files=[Path("data/sample_en.json")],
        )
        second, second_existing = build_documents_from_texts(
            ["pending retry integration"],
            seed_files=[Path("data/sample_en.json")],
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(first_existing, [])
        self.assertEqual(len(second), 1)
        self.assertEqual(second_existing, [])


if __name__ == "__main__":
    unittest.main()
