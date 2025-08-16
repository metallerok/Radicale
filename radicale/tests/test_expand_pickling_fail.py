# -*- coding: utf-8 -*-
import json
import sys
import io
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from radicale.app import Application
from radicale import config as rconfig
from radicale.storage import load as load_storage
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("radicale").setLevel(logging.DEBUG)

CAL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//radicale//EN
BEGIN:VEVENT
UID:recur-1@test
DTSTAMP:20250815T120000Z
DTSTART:20250815T090000Z
DTEND:20250815T100000Z
RRULE:FREQ=DAILY;COUNT=2
SUMMARY:demo
END:VEVENT
END:VCALENDAR
"""

def make_conf(tmp_path: Path) -> "rconfig.Configuration":
    cfg_path = tmp_path / "config"
    rights_path = tmp_path / "rights"
    rights_path.write_text(
        "[allow-all]\n"
        "user = .*\n"
        "collection = .*\n"
        "permissions = rWw\n",
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
        "[logging]\n"
        "level = debug\n"
        "trace_on_debug = true\n"
        "storage_cache_actions_on_debug = true\n"
        "[storage]\n"
        f"filesystem_folder = {tmp_path}/collections\n"
        "use_cache_subfolder_for_item = true\n"
        "use_cache_subfolder_for_history = true\n"
        "use_cache_subfolder_for_synctoken = true\n",
        encoding="utf-8",
    )
    return rconfig.load([(str(cfg_path), False)])

def _mk_app(tmp_path: Path) -> Application:
    conf = make_conf(tmp_path)
    load_storage(conf)  # ensure storage is initialized
    return Application(conf)

def _req(app, method, path, body=b"", content_type="text/xml"):
    # Minimal WSGI request with sane defaults
    env = {}
    setup_testing_defaults(env)
    env.update({
        "REQUEST_METHOD": method,
        "REMOTE_USER": "user",  # rights: allow-all matches this
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

    print(status)
    assert status.startswith(("201", "204"))

    # 3) Warm the item cache by requesting calendar-data (forces vobject parse + cache write)
    warm_xml = b"""<?xml version="1.0"?>
<C:calendar-query xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <prop>
    <C:calendar-data/>
  </prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="20250114T220000Z" end="20260121T220000Z"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""
    status, _, _ = _req(app, "REPORT", "/user/testcal/", body=warm_xml)
    assert status.startswith("207")

    # 4) Now run the same query but with <C:expand> to trigger the expand path,
    #    which should read the cached Item
    expand_xml = b"""<?xml version="1.0"?>
<C:calendar-query xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <prop>
    <C:calendar-data>
      <C:expand start="20250114T220000Z" end="20260121T220000Z"/>
    </C:calendar-data>
  </prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="20250114T220000Z" end="20260121T220000Z"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""
    status, _, body = _req(app, "REPORT", "/user/testcal/", body=expand_xml)
    # If your current bug reproduces, you may see 500 here; otherwise 207.
    assert status.startswith(("500",)), (status, body.decode("utf-8", "replace"))


if __name__ == "__main__":
    tmp_path = "/home/administrator/.var/tmp/radicale"
    test_expand_with_cache_and_item_copy_triggers_lock_path(tmp_path)
