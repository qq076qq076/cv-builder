import json
import tempfile
import unittest
from pathlib import Path

from app.storage.generation_tasks import GenerationTaskRepository


class GenerationTaskRepositoryTest(unittest.TestCase):
    def test_recover_interrupted_tasks_marks_only_active_tasks_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            tasks_path = role_path / "jobs/generation_tasks.json"
            tasks_path.parent.mkdir(parents=True)
            tasks_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "tasks": [
                            {
                                "id": "running-task",
                                "jobId": "job-1",
                                "kind": "resume",
                                "status": "running",
                            },
                            {
                                "id": "queued-task",
                                "jobId": "job-2",
                                "kind": "cover-letter",
                                "status": "queued",
                            },
                            {
                                "id": "done-task",
                                "jobId": "job-3",
                                "kind": "resume",
                                "status": "completed",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            recovered = GenerationTaskRepository(role_path).recover_interrupted_tasks()

            self.assertEqual(recovered, 2)
            tasks = GenerationTaskRepository(role_path).list_tasks()
            self.assertEqual([task.status for task in tasks], ["failed", "failed", "completed"])
            self.assertTrue(all("中斷" in task.error for task in tasks[:2]))

    def test_recovery_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "role"
            repository = GenerationTaskRepository(role_path)
            task = repository.create_task(job_id="job-1", kind="resume")

            self.assertEqual(repository.recover_interrupted_tasks(), 1)
            self.assertEqual(repository.recover_interrupted_tasks(), 0)
            self.assertEqual(repository.get_task(task.id).status, "failed")


if __name__ == "__main__":
    unittest.main()
