import unittest
import json
from unittest.mock import MagicMock

from modules.diary.model import DailyDiaryEntry, ContinuityThread
from modules.diary.manager import DiaryManager
from modules.creative.model import CreativeProject, DraftChunk
from modules.creative.manager import CreativeManager


class TestDiaryAndCreative(unittest.TestCase):
    def test_diary_entry_serialization(self):
        entry = DailyDiaryEntry(
            date="2026-10-31",
            generated_at="2026-10-31 22:00:00",
            summary="今天也是充实的一天",
            body="今天下午整理了房间，读了一会儿书。",
            tags=["日常生活", "读书"],
            continuity_thread=ContinuityThread(motif="整理房间", status="进行中"),
        )
        data = entry.to_dict()
        self.assertEqual(data["date"], "2026-10-31")
        self.assertEqual(data["summary"], "今天也是充实的一天")
        self.assertEqual(data["continuity_thread"]["motif"], "整理房间")

        restored = DailyDiaryEntry.from_dict(data)
        self.assertEqual(restored.date, "2026-10-31")
        self.assertEqual(restored.continuity_thread.status, "进行中")

    def test_creative_project_serialization_and_selection(self):
        project = CreativeProject(
            id="proj-1",
            title="星光航行",
            work_type="科幻小说",
            premise="一艘迷航在银河边缘的探索飞船",
            secret=False,
            draft_chunks=[
                DraftChunk(text="第一章：引擎轰鸣。"),
                DraftChunk(text="第二章：前方出现未知坐标。"),
            ],
        )
        data = project.to_dict()
        self.assertEqual(data["title"], "星光航行")
        self.assertEqual(len(data["draft_chunks"]), 2)

        restored = CreativeProject.from_dict(data)
        self.assertEqual(restored.current_chars, len("第一章：引擎轰鸣。第二章：前方出现未知坐标。"))

        # Test manager search / selector
        mgr = CreativeManager(MagicMock(), {}, MagicMock())
        mgr._projects = {project.id: project}
        matches = mgr.find_projects_by_selector("星光航行")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].id, "proj-1")


if __name__ == "__main__":
    unittest.main()
