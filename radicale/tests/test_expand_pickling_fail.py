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
PRODID:DAVx5/4.5.3-gplay ical4j/3.2.19 (org.withouthat.acalendarplus)
BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:STANDARD
DTSTART:19961027T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
TZNAME:CET
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19810329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
TZNAME:CEST
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:eade8055-7200-4889-a0d8-502ee4d3a26e
DTSTART;TZID=Europe/Paris:20240208T203000
DTEND;TZID=Europe/Paris:20240208T233000
CLASS:PUBLIC
CREATED:20240512T072150Z
DTSTAMP:20250815T143306Z
EXDATE;TZID=Europe/Paris:20240411T203000,20240523T203000,20240613T203000,20
 240627T203000,20240704T203000,20240605T203000,20240725T203000,20240620T203
 000,20240711T203000,20240912T203000,20240919T203000,20240926T203000,202410
 03T203000,20241010T203000,20241121T203000,20241128T203000,20241212T203000,
 20250116T203000,20250320T203000,20250410T203000,20250522T203000,20241205T2
 03000,20241226T203000,20250102T203000,20250306T203000,20250417T203000,2025
 0501T203000,20250605T203000,20250612T203000,20250619T203000,20250626T20300
 0,20250807T203000,20250703T203000,20250717T203000,20250814T203000,20250821
 T203000
RDATE;TZID=Europe/Paris:20240614T203000,20240605T203000,20240703T203000,202
 40626T203000,20240726T203000,20240920T203000,20240924T203000,20241011T2030
 00,20241129T203000,20241213T203000,20250117T203000,20250318T203000,2025040
 8T203000,20250520T203000,20250804T203000,20250812T203000,20250819T203000
RRULE:FREQ=WEEKLY;UNTIL=20370101T000000Z;BYDAY=TH
SEQUENCE:35
SUMMARY:summary
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:description
TRIGGER:-PT10M
END:VALARM
X-MOZ-GENERATION:4
X-MOZ-LASTACK:20241114T214940Z
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
    load_storage(conf)
    return Application(conf)


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

    status, _, resp = _req(
        app, "PUT", "/user/testcal/recur.ics",
        body=CAL.encode("utf-8"),
        content_type="text/calendar"
    )

    print(status)
    assert status.startswith(("201", "204"))

    expand_xml = b"""<?xml version="1.0"?>
<C:calendar-query xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <prop>
    <getetag />
    <C:calendar-data>
      <C:expand start="20250816T220000Z" end="20250823T220000Z" />
    </C:calendar-data>
  </prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="20250816T220000Z" end="20250823T220000Z" />
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""
    status, _, body = _req(app, "REPORT", "/user/testcal/", body=expand_xml)
    status, _, body = _req(app, "REPORT", "/user/testcal/", body=expand_xml)

    assert status.startswith(("207",)), (status, body.decode("utf-8", "replace"))


if __name__ == "__main__":
    tmp_path = "/home/administrator/.var/tmp/radicale"
    test_expand_with_cache_and_item_copy_triggers_lock_path(tmp_path)
