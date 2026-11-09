"""Sign in by emailed link, and the approved-people list."""
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from models import AllowedUser, LoginLink, UserSession


def _person(db, email="rob@example.com", role="admin", can_manage=False, active=True):
    u = AllowedUser(email=email, role=role, can_manage=can_manage, active=active)
    db.add(u)
    db.commit()
    return u


def _request(client, email):
    """Ask for a link; return (response, url sent in the email or None)."""
    sent = []
    with patch("send_notification.send_email", side_effect=lambda **kw: sent.append(kw) or {"status": "sent"}):
        resp = client.post("/api/signin/request", json={"email": email})
    url = None
    if sent:
        url = re.search(r"https?://\S+", sent[0]["body"]).group(0)
    return resp, url


def _token(url):
    return url.rsplit("/", 1)[1]


def _sign_in(client, db, **person):
    _person(db, **person)
    _, url = _request(client, "rob@example.com")
    resp = client.post("/api/signin/redeem", json={"token": _token(url)})
    return {"session_token": resp.cookies["session_token"]}


class TestRequest:
    def test_allowed_email_gets_a_link(self, client, db):
        _person(db)
        resp, url = _request(client, "Rob@Example.com ")           # case and spaces do not matter
        assert resp.status_code == 200
        assert url and "/signin/" in url

    def test_unknown_email_gets_the_same_answer_and_no_email(self, client, db):
        _person(db)
        known, _ = _request(client, "rob@example.com")
        unknown, url = _request(client, "nobody@example.com")
        assert url is None
        assert unknown.status_code == 200 and unknown.json() == known.json()
        assert db.query(LoginLink).count() == 1

    def test_removed_person_gets_no_link(self, client, db):
        _person(db, active=False)
        _, url = _request(client, "rob@example.com")
        assert url is None

    def test_garbage_email_is_neutral(self, client, db):
        resp, url = _request(client, "not-an-email")
        assert resp.status_code == 200 and url is None

    def test_limited_to_five_an_hour(self, client, db):
        _person(db)
        urls = [_request(client, "rob@example.com")[1] for _ in range(7)]
        assert len([u for u in urls if u]) == 5

    def test_only_a_hash_is_stored(self, client, db):
        _person(db)
        _, url = _request(client, "rob@example.com")
        assert _token(url) not in db.query(LoginLink).one().token_hash


class TestRedeem:
    def test_signs_in_with_the_persons_role(self, client, db):
        c = _sign_in(client, db, role="stakeholder")
        me = client.get("/api/auth/me", cookies=c).json()
        assert me["username"] == "rob@example.com" and me["role"] == "stakeholder"

    def test_session_lasts_seven_days(self, client, db):
        _sign_in(client, db)
        s = db.query(UserSession).one()
        assert timedelta(days=6, hours=23) < s.expires_at - datetime.utcnow() <= timedelta(days=7)

    def test_link_works_once(self, client, db):
        _person(db)
        _, url = _request(client, "rob@example.com")
        assert client.post("/api/signin/redeem", json={"token": _token(url)}).status_code == 200
        again = client.post("/api/signin/redeem", json={"token": _token(url)})
        assert again.status_code == 400 and "already used" in again.json()["detail"]

    def test_expired_link(self, client, db):
        _person(db)
        _, url = _request(client, "rob@example.com")
        link = db.query(LoginLink).one()
        link.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        resp = client.post("/api/signin/redeem", json={"token": _token(url)})
        assert resp.status_code == 400 and "expired" in resp.json()["detail"]
        assert db.query(UserSession).count() == 0

    def test_made_up_token(self, client, db):
        assert client.post("/api/signin/redeem", json={"token": "x" * 40}).status_code == 400

    def test_person_removed_after_link_was_sent(self, client, db):
        p = _person(db)
        _, url = _request(client, "rob@example.com")
        p.active = False
        db.commit()
        assert client.post("/api/signin/redeem", json={"token": _token(url)}).status_code == 400

    def test_asking_for_a_link_does_not_use_it_up(self, client, db):
        _person(db)
        _request(client, "rob@example.com")
        assert db.query(LoginLink).one().used_at is None


class TestManageList:
    def test_shared_password_admin_can_manage(self, client, db, auth_cookies):
        resp = client.post("/api/users", json={"email": "New@Example.com", "name": "New", "role": "admin"}, cookies=auth_cookies)
        assert resp.status_code == 200 and resp.json()["email"] == "new@example.com"
        listing = client.get("/api/users", cookies=auth_cookies).json()
        assert listing["can_manage"] and len(listing["users"]) == 1

    def test_link_user_without_manage_cannot(self, client, db):
        c = _sign_in(client, db)
        assert client.post("/api/users", json={"email": "x@example.com"}, cookies=c).status_code == 403
        assert client.get("/api/users", cookies=c).json() == {"can_manage": False, "users": []}

    def test_link_user_with_manage_can(self, client, db):
        c = _sign_in(client, db, can_manage=True)
        assert client.post("/api/users", json={"email": "x@example.com"}, cookies=c).status_code == 200

    def test_stakeholder_cannot_manage(self, client, db):
        c = _sign_in(client, db, role="stakeholder", can_manage=True)
        assert client.post("/api/users", json={"email": "x@example.com"}, cookies=c).status_code == 403

    def test_needs_login(self, client, db):
        assert client.get("/api/users").status_code == 401
        assert client.post("/api/users", json={"email": "x@example.com"}).status_code == 401

    def test_bad_email_and_role(self, client, db, auth_cookies):
        assert client.post("/api/users", json={"email": "nope"}, cookies=auth_cookies).status_code == 422
        assert client.post("/api/users", json={"email": "a@b.co", "role": "root"}, cookies=auth_cookies).status_code == 422

    def test_removing_a_person_ends_their_session_and_blocks_new_links(self, client, db, auth_cookies):
        p = _person(db)
        _, url = _request(client, "rob@example.com")
        client.post("/api/signin/redeem", json={"token": _token(url)})
        assert db.query(UserSession).filter(UserSession.username == "rob@example.com").count() == 1
        resp = client.patch(f"/api/users/{p.id}", json={"active": False}, cookies=auth_cookies)
        assert resp.status_code == 200 and resp.json()["active"] is False
        assert db.query(UserSession).filter(UserSession.username == "rob@example.com").count() == 0
        assert _request(client, "rob@example.com")[1] is None

    def test_adding_again_reactivates(self, client, db, auth_cookies):
        _person(db, active=False)
        client.post("/api/users", json={"email": "rob@example.com"}, cookies=auth_cookies)
        assert db.query(AllowedUser).one().active is True


class TestPasswordLoginStillWorks:
    def test_password_login_unchanged(self, client, db):
        from conftest import _TEST_PASSWORD
        resp = client.post("/api/auth/login", json={"username": "admin", "password": _TEST_PASSWORD})
        assert resp.status_code == 200
