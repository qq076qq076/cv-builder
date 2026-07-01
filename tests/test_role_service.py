import tempfile
import unittest
from pathlib import Path

from app.schemas.resume import NormalizedResume, ResumeExperience
from app.schemas.role import RoleProfile
from app.services.role_service import RoleService


class RoleServiceTest(unittest.TestCase):
    def test_create_role_creates_role_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = RoleService(workspace)

            role = service.create_role("Walker Lin")

            self.assertEqual(role.id, "walker-lin")
            self.assertTrue((workspace / "walker-lin/metadata.json").is_file())
            self.assertTrue((workspace / "walker-lin/evidence/files").is_dir())
            self.assertTrue((workspace / "walker-lin/evidence/profile.json").is_file())
            self.assertFalse(service.load_profile(role.id).name)

    def test_list_roles_ignores_legacy_workspace_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            (workspace / "evidence").mkdir(parents=True)
            service = RoleService(workspace)
            service.create_role("Walker")

            roles = service.list_roles()

            self.assertEqual([role.id for role in roles], ["walker"])

    def test_save_profile_writes_to_role_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = RoleService(workspace)
            role = service.create_role("Walker")

            service.save_profile(
                role.id,
                RoleProfile(
                    name="Walker Lin",
                    skills="Python\nAngular",
                    career="Frontend Engineer",
                    autobiography="Hello",
                ),
            )

            profile = service.load_profile(role.id)
            self.assertEqual(profile.name, "Walker Lin")
            self.assertIn("Python", profile.skills)

    def test_sync_profile_from_resume_fills_empty_fields_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = RoleService(workspace)
            role = service.create_role("Walker")
            service.save_profile(role.id, RoleProfile(name="Manual Name"))

            service.sync_profile_from_resume(
                role.id,
                NormalizedResume(
                    name="AI Name",
                    skills=["Python", "FastAPI"],
                    summary="Backend engineer",
                    autobiography="AI bio",
                    experiences=[
                        ResumeExperience(
                            company="Acme",
                            title="Engineer",
                            startDate="2020",
                            endDate="2024",
                            summary="Built APIs",
                        )
                    ],
                ),
            )

            profile = service.load_profile(role.id)
            self.assertEqual(profile.name, "Manual Name")
            self.assertEqual(profile.skills, "Python\nFastAPI")
            self.assertIn("Backend engineer", profile.career)
            self.assertIn("Engineer @ Acme", profile.career)
            self.assertEqual(profile.autobiography, "AI bio")


if __name__ == "__main__":
    unittest.main()
