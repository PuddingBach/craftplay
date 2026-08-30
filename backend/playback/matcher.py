from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.playback.validation import normalized_title
from backend.schemas import MediaItem


@dataclass(frozen=True)
class MatchResult:
    score: int
    accepted: bool
    reasons: list[str]


class MediaMatcher:
    """Scores candidates using titles plus structured metadata."""

    threshold = 70

    def match(self, media: MediaItem, candidate: dict, season: int = 0, episode: int = 0) -> MatchResult:
        candidate_title = normalized_title(str(candidate.get("title", "")))
        primary = normalized_title(media.title)
        alternatives = [normalized_title(value) for value in [media.original_title, *media.tags] if value]
        score, reasons = 0, []
        similarity = SequenceMatcher(None, primary, candidate_title).ratio()
        if similarity >= 0.86:
            score += 50; reasons.append("title")
        elif any(SequenceMatcher(None, alternative, candidate_title).ratio() >= 0.86 for alternative in alternatives):
            score += 40; reasons.append("alternative_title")
        if media.year and candidate.get("year") and abs(int(candidate["year"]) - media.year) <= 1:
            score += 20; reasons.append("year")
        expected_type = "tv" if media.media_type in {"series", "anime", "cartoon"} else "movie"
        if candidate.get("media_type") in {None, expected_type, media.media_type}:
            score += 20; reasons.append("media_type")
        if season:
            if int(candidate.get("season", -1)) == season:
                score += 20; reasons.append("season")
            else:
                return MatchResult(score, False, [*reasons, "season_mismatch"])
        if episode:
            if int(candidate.get("episode", -1)) == episode:
                score += 30; reasons.append("episode")
            else:
                return MatchResult(score, False, [*reasons, "episode_mismatch"])
        return MatchResult(score, score >= self.threshold, reasons)
