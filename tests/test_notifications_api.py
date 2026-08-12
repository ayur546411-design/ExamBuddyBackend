from app.main import app


def test_notifications_api_route_exists():
    routes = [route.path for route in app.routes]
    assert "/api/v1/notifications/" in routes
