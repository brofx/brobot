from __future__ import annotations

"""
Disc Golf League Scraper (schedule + participants + grouping util)

Pyodide note:
  If you run this in Pyodide and want timezone-aware comparisons, load tzdata:

      await pyodide.loadPackage('tzdata')

If tzdata/ZoneInfo is unavailable, this script falls back to using the
system-local date for classification.
"""

from dataclasses import dataclass
from typing import List, Optional, Iterable, Tuple
from datetime import datetime, date
import re
import random
import requests
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:
    ZoneInfo = None  # type: ignore


@dataclass(frozen=True)
class LeagueEvent:
    """A single league event scraped from a UDisc league schedule.

    Attributes:
        event_date: The calendar date of the event (league round start date).
        name: The event name (e.g., "BRFX Y5W20").
        course_layout: The course and layout information (e.g., "Top O' The Hill (Main)").
        event_slug: The UDisc event slug extracted from the href (e.g., "abcd-12345").
        is_upcoming: True if the event is upcoming, False if it is in the past.
    """

    event_date: date
    name: str
    course_layout: str
    event_slug: str
    is_upcoming: bool


@dataclass(frozen=True)
class Participant:
    """A single participant on an event's participants page.

    Attributes:
        display_name: The user's display name as shown on the page.
        username: Their handle (without the leading '@').
        avatar_url: URL of the user's avatar image, if present.
    """

    display_name: str
    username: str
    avatar_url: str


class DiscGolfLeague:
    """Scraper for UDisc league schedules and participants."""

    _SCHEDULE_URL_TEMPLATE = "https://udisc.com/leagues/{slug}/schedule"
    _EVENT_PARTICIPANTS_URL_TEMPLATE = "https://udisc.com/events/{event_slug}/participants"

    def __init__(
        self,
        url_slug: str,
        *,
        timezone: Optional[str] = "America/New_York",
        session: Optional[requests.Session] = None,
    ) -> None:
        self.url_slug = url_slug
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.8",
            }
        )

        self._tz = None  # type: Optional[object]
        if timezone and ZoneInfo is not None:
            try:
                self._tz = ZoneInfo(timezone)  # type: ignore[arg-type]
            except Exception:
                self._tz = None

    # -------------------- Public API --------------------
    def get_events(self, num_upcoming: int = 5, num_past: int = 0) -> List[LeagueEvent]:
        """Return up to `num_upcoming` upcoming and `num_past` past events."""
        n_up = max(0, min(5, int(num_upcoming)))
        n_past = max(0, min(5, int(num_past)))

        html = self._fetch(self._schedule_url)
        upcoming, past = self._parse_page(html)
        return upcoming[:n_up] + past[:n_past]

    def get_event_participants(self, event_slug: str) -> List[Participant]:
        """Fetch and parse the participants for a given event slug."""
        url = self._EVENT_PARTICIPANTS_URL_TEMPLATE.format(event_slug=event_slug)
        html = self._fetch(url)
        return list(self._parse_participants(html))

    # -------------------- Internals --------------------
    @property
    def _schedule_url(self) -> str:
        return self._SCHEDULE_URL_TEMPLATE.format(slug=self.url_slug)

    def _today(self) -> date:
        if self._tz is not None:
            try:
                return datetime.now(self._tz).date()  # type: ignore[arg-type]
            except Exception:
                pass
        return date.today()

    def _fetch(self, url: str) -> str:
        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def _parse_page(self, html: str) -> Tuple[List[LeagueEvent], List[LeagueEvent]]:
        """Parse both Upcoming and Past sections.

        Returns:
            (upcoming_events, past_events)
        """
        soup = BeautifulSoup(html, "html.parser")

        def _is_heading(tag) -> bool:
            return tag.name in {"h1", "h2", "h3", "h4"}

        # Locate headings
        upcoming_hdr = None
        past_hdr = None
        for h in soup.find_all(_is_heading):
            text = h.get_text(strip=True).lower()
            if upcoming_hdr is None and text.startswith("upcoming"):
                upcoming_hdr = h
            elif past_hdr is None and text.startswith("past"):
                past_hdr = h

        upcoming: List[LeagueEvent] = []
        past: List[LeagueEvent] = []

        # Helper to walk anchors from a starting heading until we hit another heading
        def _collect_from(start_hdr, is_upcoming_flag: bool) -> List[LeagueEvent]:
            out: List[LeagueEvent] = []
            if not start_hdr:
                return out
            for node in start_hdr.find_all_next():
                if _is_heading(node) and node is not start_hdr:
                    # Stop at the next section heading
                    break
                if node.name == "a":
                    href = (node.get("href") or "").strip()
                    if not href.startswith("/events"):
                        continue
                    text = " ".join(node.get_text(" ", strip=True).split())
                    evt = self._parse_event_line(text, href, is_upcoming_flag)
                    if evt:
                        out.append(evt)
            return out

        upcoming = _collect_from(upcoming_hdr, True)
        past = _collect_from(past_hdr, False)

        # Fallback: if no headings found, try to classify by date
        if not upcoming and not past:
            today = self._today()
            for a in soup.find_all("a"):
                href = (a.get("href") or "").strip()
                if not href.startswith("/events"):
                    continue
                text = " ".join(a.get_text(" ", strip=True).split())
                evt = self._parse_event_line(text, href, True)
                if evt:
                    is_up = evt.event_date >= today
                    evt = LeagueEvent(
                        event_date=evt.event_date,
                        name=evt.name,
                        course_layout=evt.course_layout,
                        event_slug=evt.event_slug,
                        is_upcoming=is_up,
                    )
                    (upcoming if is_up else past).append(evt)

        return upcoming, past

    _LINE_RE = re.compile(
        r"^\s*(?P<month>[A-Za-z]+)\s+"
        r"(?P<day>\d{1,2})\s+"
        r"(?P<name>.+?)\s+"
        r"(?P<year>\d{4})\s+"
        r"(?P<course>[^•\n]+)",
        re.UNICODE,
    )

    _EVENT_SLUG_RE = re.compile(r"^/events/([^/?#]+)")

    @staticmethod
    def _parse_date(month: str, day: str, year: str) -> date:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{month} {int(day)} {year}", fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unrecognized date: {month} {day} {year}")

    def _parse_event_line(self, text: str, href: str, is_upcoming_flag: bool) -> Optional[LeagueEvent]:
        """Extract fields from a schedule line.

        Example shape:
          "Aug 26 BRFX Y5W20 2025 Top O' The Hill (Main) • Canterbury, NH 5:15 PM - 8:00 PM Tue"

        We only need the date, event name, course/layout (before the •), and event slug.
        """
        m = self._LINE_RE.search(text)
        if not m:
            return None

        slug_m = self._EVENT_SLUG_RE.search(href)
        if not slug_m:
            return None
        event_slug = slug_m.group(1)

        event_dt = self._parse_date(m.group("month"), m.group("day"), m.group("year"))
        name = m.group("name").strip()
        course_layout = m.group("course").strip()
        return LeagueEvent(
            event_date=event_dt,
            name=name,
            course_layout=course_layout,
            event_slug=event_slug,
            is_upcoming=is_upcoming_flag,
        )

    # -------- Participants parsing --------
    def _parse_participants(self, html: str) -> Iterable['Participant']:
        """Yield participants from an event participants page.

        The page uses flexbox rows; each row contains an <img> avatar, a display name
        in a <p class="mb-1 ..."> element, and a handle like "@amelia" within a
        subtle text block. We extract those fields and strip the leading '@'.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Find the "Participants" header text node, then walk to the list container
        header_label = soup.find(lambda t: getattr(t, "name", None) and t.get_text(strip=True) == "Participants")
        list_container = None
        if header_label is not None:
            # The header text is inside a <div> within a flex header row; the list
            # container is usually the next sibling <div class="... flex-col ...">
            header_row = header_label.find_parent("div")
            if header_row is not None:
                list_container = header_row.find_next_sibling("div")

        # If we couldn't locate via header, fall back to any flex-col container with spacing
        if list_container is None:
            list_container = soup.find("div", class_=re.compile(r"\bflex-col\b"))

        if list_container is None:
            return  # Nothing to yield

        # Each participant row tends to be a flex row with items-center & justify-between
        row_sel = re.compile(r"\bflex\b.*\bitems-center\b.*\bjustify-between\b")
        rows = [d for d in list_container.find_all("div", class_=row_sel, recursive=True)]
        seen = set()
        for row in rows:
            # Avatar
            img = row.find("img")
            avatar_url = (img.get("src") or "").strip() if img else ""

            # Display name
            name_tag = row.find("p", class_=re.compile(r"\bmb-1\b"))
            display_name = (name_tag.get_text(strip=True) if name_tag else "").strip()

            # Username (prefixed with '@' in the markup)
            handle_tag = row.find(lambda t: getattr(t, "name", None) == "p" and isinstance(t.string, str) and t.string.strip().startswith("@"))
            username = handle_tag.string.strip()[1:] if handle_tag and isinstance(handle_tag.string, str) else ""

            key = (display_name, username, avatar_url)
            if display_name and key not in seen:
                seen.add(key)
                yield Participant(display_name=display_name, username=username, avatar_url=avatar_url)

    def get_event_participants(self, event_slug: str) -> List['Participant']:
        """Fetch and parse the participants for a given event slug."""
        url = self._EVENT_PARTICIPANTS_URL_TEMPLATE.format(event_slug=event_slug)
        html = self._fetch(url)
        return list(self._parse_participants(html))


# -------------------- Grouping util --------------------

def group_participants(participants: List['Participant'], *, rng: Optional[random.Random] = None) -> List[List['Participant']]:
    """Randomly assign participants into groups following size rules.

    Rules:
      - 1..5 players: one group containing all players.
      - Otherwise, groups must be size 2..4, as equal as possible.
      - Optimize for **fewer groups** while staying within constraints.
      - Smaller groups should be placed **in front of** larger groups.

    Returns:
      A list of groups (each group is a list of Participant), ordered with
      smaller groups first.
    """
    n = len(participants)
    if n <= 0:
        return []
    if n <= 5:
        # Single group (even if that means size 1 or 5)
        shuffled = participants.copy()
        (rng or random).shuffle(shuffled)
        return [shuffled]

    # Compute target sizes using 2/3/4 (favor fewer groups, then equality)
    sizes = _best_group_sizes(n)

    # Shuffle participants then allocate in ascending size order
    shuffled = participants.copy()
    (rng or random).shuffle(shuffled)
    sizes.sort()  # smaller groups first

    groups: List[List[Participant]] = []
    idx = 0
    for sz in sizes:
        groups.append(shuffled[idx: idx + sz])
        idx += sz
    return groups


def _best_group_sizes(n: int) -> List[int]:
    """Partition n into sizes from {2,3,4}.

    Optimization priorities (lexicographic, lower is better):
      1) **Minimize number of groups** (favor fewer groups)
      2) Minimize size range (max(size) - min(size))  [favor equal sizes]
      3) Minimize count of 2s                          [avoid small groups]
      4) Prefer more 4s if still tied                  [aligns with examples]
    """
    best: Optional[Tuple[Tuple[int, ...], Tuple[int, int, int, int]]] = None
    # Explore all c (4s), b (3s), a (2s)
    for c in range(n // 4, -1, -1):
        remain_after_4 = n - 4 * c
        for b in range(remain_after_4 // 3, -1, -1):
            remain = remain_after_4 - 3 * b
            if remain < 0:
                continue
            if remain % 2 != 0:
                continue
            a = remain // 2
            if a < 0:
                continue
            sizes = (4,) * c + (3,) * b + (2,) * a
            if not sizes:
                continue
            rng_size = max(sizes) - min(sizes)
            num_groups = len(sizes)
            num_twos = sizes.count(2)
            # Metric tuple: lower is better
            metric = (num_groups, rng_size, num_twos, -sizes.count(4))
            if best is None or metric < best[1]:
                best = (sizes, metric)
    if best is None:
        # Fallback shouldn't happen for n>=6, but return pairs of 2s and a trailing 3/4
        q, r = divmod(n, 4)
        sizes = [4] * q
        if r:
            if r == 1:
                sizes[-1] = 3
                sizes.append(2)
            else:
                sizes.append(r)
        return sizes
    return list(best[0])
