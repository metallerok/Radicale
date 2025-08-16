import sys
import json
import os
import io
import pickle
import tempfile
import datetime as dt
from wsgiref.validate import validator
from radicale.app import Application
from radicale import config as rconfig
from radicale.app import Application  # или ваш путь до приложения
from radicale.storage import load as load_storage
from pathlib import Path
from wsgiref.util import setup_testing_defaults

CAL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:+//IDN bitfire.at//ical4android (at.techbee.jtx)
BEGIN:VJOURNAL
CREATED:20240420T135521Z
DESCRIPTION:Some data
DTSTART:20240420T150537Z
LAST-MODIFIED:20240420T150533Z
SEQUENCE:18
STATUS:FINAL
SUMMARY:Title of the entry
UID:8eddaf11-e50a-4b7b-8689-7aada4259890
END:VJOURNAL
END:VCALENDAR
"""


def make_conf(tmp_path: Path) -> "rconfig.Configuration":
    cfg_path = tmp_path / "config"
    rights_path = tmp_path / "rights"

    rights_path.write_text(
        "[allow-all]\n"
        "user = .*\n"
        "collection = .*\n"
        "permissions = rwW\n",
        encoding="utf-8",
    )

    cfg_path.write_text(
        "[server]\n"
        "hosts = 127.0.0.1:0\n"
        "\n"
        "[auth]\n"
        "type = none\n"
        "\n"
        "[rights]\n"
        "type = from_file\n"
        f"file = {rights_path}\n"
        "\n"
        "[storage]\n"
        f"filesystem_folder = {tmp_path}/collections\n",
        encoding="utf-8",
    )
    return rconfig.load([(str(cfg_path), False)])


def _mk_app(tmp_path: Path) -> Application:
    conf = make_conf(tmp_path)
    storage = load_storage(conf)
    app = Application(conf)
    return app


def _req(app, method, path, body=b"", content_type="text/xml"):
    env = {}
    setup_testing_defaults(env)

    env.update({
        "REQUEST_METHOD": method,
        "REMOTE_USER": "user",
        "PATH_INFO": path,
        "SCRIPT_NAME": "",
        "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "HTTP_DEPTH": "1",
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.errors": sys.stderr,
    })

    status_headers_body = []

    def start_response(status, headers, exc_info=None):
        status_headers_body[:] = [status, headers]

    body_iter = app(env, start_response)
    out = b"".join(body_iter)

    print("=== REQ", method, path)
    print("=== STATUS", status_headers_body[0])
    print("=== HEADERS", dict(status_headers_body[1]))
    if out:
        print("=== BODY", out.decode("utf-8", "replace"))

    return status_headers_body[0], dict(status_headers_body[1]), out


def test_expand_with_cache_and_item_copy_triggers_lock_path(tmp_path):
    app = _mk_app(Path(tmp_path))

    status, _, _ = _req(app, "MKCOL", "/user/")
    assert status.startswith(("201", "405")), status

    status, _, _ = _req(app, "MKCOL", "/user/testcal/")
    assert status.startswith(("201", "405")), status

    root = Path(tmp_path) / "collections" / "collection-root" / "user" / "testcal"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".Radicale.props").write_text(json.dumps({"tag": "VCALENDAR"}), encoding="utf-8")

    status, _, resp = _req(app, "PUT", "/user/testcal/recur.ics",
                        body=CAL.encode("utf-8"),
                        content_type="text/calendar")

    assert status.startswith(("201", "405", "204"))

    # 1) warm the item cache (no expand)
    warm_xml = b"""<?xml version="1.0"?>
    <C:calendar-query xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
    <prop><D:getetag xmlns:D="DAV:"/></prop>
    <C:filter>
        <C:comp-filter name="VCALENDAR">
        <C:comp-filter name="VJOURNAL">
            <C:time-range start="20230814T220000Z" end="20250821T220000Z"/>
        </C:comp-filter>
        </C:comp-filter>
    </C:filter>
    </C:calendar-query>"""
    status, _, _ = _req(app, "REPORT", "/user/testcal/", body=warm_xml)
    assert status.startswith("207"), status

    # 2) now the same query but with <C:expand> to trigger the bug path
    expand_xml = b"""<?xml version="1.0"?>
    <C:calendar-query xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
    <prop>
        <C:calendar-data>
        <C:expand start="20230814T220000Z" end="20250821T220000Z"/>
        </C:calendar-data>
    </prop>
    <C:filter>
        <C:comp-filter name="VCALENDAR">
        <C:comp-filter name="VJOURNAL">
            <C:time-range start="20230814T220000Z" end="20250821T220000Z"/>
        </C:comp-filter>
        </C:comp-filter>
    </C:filter>
    </C:calendar-query>"""
    status, _, body = _req(app, "REPORT", "/user/testcal/", body=expand_xml)
    print(body)
    assert status.startswith("500")


if __name__ == "__main__":
    tmp_path = "/home/administrator/.var/tmp/radicale"
    test_expand_with_cache_and_item_copy_triggers_lock_path(tmp_path)
