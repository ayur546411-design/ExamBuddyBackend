import pytest

from app.api.v1.endpoints.feedback import submit_feedback
from app.models.userfeedback import UserFeedback
from app.schemas.userfeedback import UserFeedbackCreate


class FakeSession:
    def __init__(self):
        self.items = []

    def add(self, obj):
        self.items.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.created_at = "2024-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_submit_feedback_without_auth_works(monkeypatch):
    async def fake_ensure_feedback_table():
        return None

    monkeypatch.setattr(
        'app.api.v1.endpoints.feedback.ensure_feedback_table',
        fake_ensure_feedback_table,
    )

    payload = UserFeedbackCreate(
        full_name="Jane Doe",
        feedback_type="Suggestion",
        message="The app is working well.",
        school_id="school-123",
        department_id="dept-456",
    )

    result = await submit_feedback(payload=payload, db=FakeSession(), current_user=None)

    assert isinstance(result, UserFeedback)
    assert result.full_name == "Jane Doe"
    assert result.message == "The app is working well."
    assert result.user_id is None
    assert result.school_id == "school-123"
    assert result.department_id == "dept-456"
