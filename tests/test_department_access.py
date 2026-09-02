import pytest

from app.api.v1.endpoints.documents import get_documents
from app.models.user import User, UserRoleEnum


class DummyScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class DummyResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return DummyScalarResult(self._rows)


class DummySession:
    async def execute(self, query):
        return DummyResult([])


@pytest.mark.asyncio
async def test_admin_can_list_documents_without_department_assignment():
    admin_user = User(
        id="admin-1",
        full_name="Admin User",
        hashed_password="dummy",
        role=UserRoleEnum.admin,
        is_admin=True,
        department_id=None,
        school_id=None,
    )

    documents = await get_documents(db=DummySession(), current_user=admin_user)

    assert documents == []
