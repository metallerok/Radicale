# This file is part of Radicale - CalDAV and CardDAV server
# Copyright © 2012-2017 Guillaume Ayoub
# Copyright © 2017-2019 Unrud <unrud@outlook.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Radicale.  If not, see <http://www.gnu.org/licenses/>.

"""
Radicale tests with expand requests.

"""

import os
from typing import ClassVar, List

from radicale.tests import BaseTest
from radicale.tests.helpers import get_file_content
from radicale.log import logger

from xml.etree import ElementTree

ONLY_DATES = True
CONTAINS_TIMES = False


class TestExpandRequests(BaseTest):
    """Tests with expand requests."""

    # Allow skipping sync-token tests, when not fully supported by the backend
    full_sync_token_support: ClassVar[bool] = True

    def setup_method(self) -> None:
        BaseTest.setup_method(self)
        rights_file_path = os.path.join(self.colpath, "rights")
        with open(rights_file_path, "w") as f:
            f.write("""\
[permit delete collection]
user: .*
collection: test-permit-delete
permissions: RrWwD

[forbid delete collection]
user: .*
collection: test-forbid-delete
permissions: RrWwd

[permit overwrite collection]
user: .*
collection: test-permit-overwrite
permissions: RrWwO

[forbid overwrite collection]
user: .*
collection: test-forbid-overwrite
permissions: RrWwo

[allow all]
user: .*
collection: .*
permissions: RrWw""")
        self.configure({"rights": {"file": rights_file_path,
                                   "type": "from_file"}})

    def _test_expand(self,
                     expected_uid: str,
                     start: str,
                     end: str,
                     expected_recurrence_ids: List[str],
                     expected_start_times: List[str],
                     expected_end_times: List[str],
                     only_dates: bool,
                     nr_uids: int) -> None:
        self.put("/calendar.ics/", get_file_content(f"{expected_uid}.ics"))
        req_body_without_expand = \
            f"""<?xml version="1.0" encoding="utf-8" ?>
            <C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
                <D:prop>
                    <C:calendar-data>
                    </C:calendar-data>
                </D:prop>
                <C:filter>
                    <C:comp-filter name="VCALENDAR">
                        <C:comp-filter name="VEVENT">
                            <C:time-range start="{start}" end="{end}"/>
                        </C:comp-filter>
                    </C:comp-filter>
                </C:filter>
            </C:calendar-query>
            """
        _, responses = self.report("/calendar.ics/", req_body_without_expand)
        assert len(responses) == 1

        response_without_expand = responses[f'/calendar.ics/{expected_uid}.ics']
        assert not isinstance(response_without_expand, int)
        status, element = response_without_expand["C:calendar-data"]

        assert status == 200 and element.text

        assert "RRULE" in element.text
        if not only_dates:
            assert "BEGIN:VTIMEZONE" in element.text
        if nr_uids == 1:
            assert "RECURRENCE-ID" not in element.text

        uids: List[str] = []
        for line in element.text.split("\n"):
            if line.startswith("UID:"):
                uid = line[len("UID:"):]
                assert uid == expected_uid
                uids.append(uid)

        assert len(uids) == nr_uids

        req_body_with_expand = \
            f"""<?xml version="1.0" encoding="utf-8" ?>
            <C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
                <D:prop>
                    <C:calendar-data>
                        <C:expand start="{start}" end="{end}"/>
                    </C:calendar-data>
                </D:prop>
                <C:filter>
                    <C:comp-filter name="VCALENDAR">
                        <C:comp-filter name="VEVENT">
                            <C:time-range start="{start}" end="{end}"/>
                        </C:comp-filter>
                    </C:comp-filter>
                </C:filter>
            </C:calendar-query>
            """

        _, responses = self.report("/calendar.ics/", req_body_with_expand)

        assert len(responses) == 1

        response_with_expand = responses[f'/calendar.ics/{expected_uid}.ics']
        assert not isinstance(response_with_expand, int)
        status, element = response_with_expand["C:calendar-data"]

        logger.debug("lbt: element is %s",
                     ElementTree.tostring(element, encoding='unicode'))
        assert status == 200 and element.text
        assert "RRULE" not in element.text
        assert "BEGIN:VTIMEZONE" not in element.text

        uids = []
        recurrence_ids = []
        for line in element.text.split("\n"):
            if line.startswith("UID:"):
                assert line == f"UID:{expected_uid}"
                uids.append(line)

            if line.startswith("RECURRENCE-ID:"):
                assert line in expected_recurrence_ids
                recurrence_ids.append(line)

            if line.startswith("DTSTART:"):
                assert line in expected_start_times

            if line.startswith("DTEND:"):
                assert line in expected_end_times

        assert len(uids) == len(expected_recurrence_ids)
        assert len(set(recurrence_ids)) == len(expected_recurrence_ids)

    def test_report_with_expand_property(self) -> None:
        """Test report with expand property"""
        self._test_expand(
            "event_daily_rrule",
            "20060103T000000Z",
            "20060105T000000Z",
            ["RECURRENCE-ID:20060103T170000Z", "RECURRENCE-ID:20060104T170000Z"],
            ["DTSTART:20060103T170000Z", "DTSTART:20060104T170000Z"],
            [],
            CONTAINS_TIMES,
            1
        )

    def test_report_with_expand_property_start_inside(self) -> None:
        """Test report with expand property start inside"""
        self._test_expand(
            "event_daily_rrule",
            "20060103T171500Z",
            "20060105T000000Z",
            ["RECURRENCE-ID:20060103T170000Z", "RECURRENCE-ID:20060104T170000Z"],
            ["DTSTART:20060103T170000Z", "DTSTART:20060104T170000Z"],
            [],
            CONTAINS_TIMES,
            1
        )

    def test_report_with_expand_property_just_inside(self) -> None:
        """Test report with expand property start and end inside event"""
        self._test_expand(
            "event_daily_rrule",
            "20060103T171500Z",
            "20060103T171501Z",
            ["RECURRENCE-ID:20060103T170000Z"],
            ["DTSTART:20060103T170000Z"],
            [],
            CONTAINS_TIMES,
            1
        )

    def test_report_with_expand_property_issue1812(self) -> None:
        """Test report with expand property for issue 1812"""
        self._test_expand(
            "event_issue1812",
            "20250127T183000Z",
            "20250127T183001Z",
            ["RECURRENCE-ID:20250127T180000Z"],
            ["DTSTART:20250127T180000Z"],
            ["DTEND:20250127T233000Z"],
            CONTAINS_TIMES,
            11
        )

    def test_report_with_expand_property_issue1812_DS(self) -> None:
        """Test report with expand property for issue 1812 - DS active"""
        self._test_expand(
            "event_issue1812",
            "20250627T183000Z",
            "20250627T183001Z",
            ["RECURRENCE-ID:20250627T170000Z"],
            ["DTSTART:20250627T170000Z"],
            ["DTEND:20250627T223000Z"],
            CONTAINS_TIMES,
            11
        )

    def test_report_with_expand_property_all_day_event(self) -> None:
        """Test report with expand property for all day events"""
        self._test_expand(
            "event_full_day_rrule",
            "20060103T000000Z",
            "20060105T000000Z",
            ["RECURRENCE-ID:20060103", "RECURRENCE-ID:20060104", "RECURRENCE-ID:20060105"],
            ["DTSTART:20060103", "DTSTART:20060104", "DTSTART:20060105"],
            ["DTEND:20060104", "DTEND:20060105", "DTEND:20060106"],
            ONLY_DATES,
            1
        )

    def test_report_with_expand_property_overridden(self) -> None:
        """Test report with expand property with overridden events"""
        self._test_expand(
            "event_daily_rrule_overridden",
            "20060103T000000Z",
            "20060105T000000Z",
            ["RECURRENCE-ID:20060103T170000Z", "RECURRENCE-ID:20060104T170000Z"],
            ["DTSTART:20060103T170000Z", "DTSTART:20060104T190000Z"],
            [],
            CONTAINS_TIMES,
            2
        )

    def test_report_with_expand_property_timezone(self):
        self._test_expand(
            "event_weekly_rrule",
            "20060320T000000Z",
            "20060414T000000Z",
            [
                "RECURRENCE-ID:20060321T200000Z",
                "RECURRENCE-ID:20060328T200000Z",
                "RECURRENCE-ID:20060404T190000Z",
                "RECURRENCE-ID:20060411T190000Z",
            ],
            [
                "DTSTART:20060321T200000Z",
                "DTSTART:20060328T200000Z",
                "DTSTART:20060404T190000Z",
                "DTSTART:20060411T190000Z",
            ],
            [],
            CONTAINS_TIMES,
            1
        )
