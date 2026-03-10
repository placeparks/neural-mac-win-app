"""
Skill Economy — Credit-based marketplace economy with ratings.

Tracks skill usage, author revenue, community ratings, and generates
leaderboards to incentivize high-quality skill contributions.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AuthorProfile:
    """A skill author in the marketplace economy."""
    author_id: str
    display_name: str
    credits: float = 0.0
    total_earnings: float = 0.0
    skills_published: int = 0
    total_installs: int = 0
    average_rating: float = 0.0
    joined_at: float = field(default_factory=time.time)

    @property
    def reputation_score(self) -> float:
        """Composite reputation = avg_rating * trust_factor * activity_factor."""
        if self.skills_published == 0:
            return 0.0
        trust = min(1.0, self.total_installs / 100)
        activity = min(1.0, self.skills_published / 10)
        return round(self.average_rating * 0.6 + trust * 0.25 + activity * 0.15, 2)


@dataclass
class SkillRating:
    """A rating for a skill."""
    skill_name: str
    rater_id: str
    score: float          # 1.0 - 5.0
    review: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class UsageRecord:
    """A single usage event for a skill."""
    skill_name: str
    user_id: str
    success: bool
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SkillEconomyStats:
    """Economy-level statistics for a skill."""
    skill_name: str
    total_uses: int = 0
    successful_uses: int = 0
    unique_users: int = 0
    average_rating: float = 0.0
    total_ratings: int = 0
    credits_earned: float = 0.0
    trend_score: float = 0.0     # Recent popularity (higher = trending)


# ---------------------------------------------------------------------------
# Skill Economy
# ---------------------------------------------------------------------------

class SkillEconomy:
    """
    Credit-based economy for the skill marketplace.

    Features:
    - Credit rewards for skill authors on each use
    - Community ratings (1-5) with reviews
    - Usage tracking and analytics
    - Popularity trending algorithm
    - Author leaderboards
    """

    CREDITS_PER_USE = 0.1          # Credits earned per skill invocation
    CREDITS_PER_INSTALL = 0.5      # Bonus credits per install
    TREND_DECAY = 0.95             # Daily decay factor for trend scores
    TREND_WINDOW = 7 * 86400       # 7-day trending window

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else Path.home() / ".neuralclaw" / "economy"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._authors: dict[str, AuthorProfile] = {}
        self._ratings: dict[str, list[SkillRating]] = {}    # skill_name → ratings
        self._usage: dict[str, list[UsageRecord]] = {}      # skill_name → usage records
        self._skill_authors: dict[str, str] = {}             # skill_name → author_id
        self._stats: dict[str, SkillEconomyStats] = {}

        self._load()

    # -- Author management --------------------------------------------------

    def register_author(self, author_id: str, display_name: str) -> AuthorProfile:
        """Register a new author in the economy."""
        if author_id not in self._authors:
            self._authors[author_id] = AuthorProfile(
                author_id=author_id,
                display_name=display_name,
            )
        return self._authors[author_id]

    def get_author(self, author_id: str) -> AuthorProfile | None:
        return self._authors.get(author_id)

    def register_skill(self, skill_name: str, author_id: str) -> None:
        """Associate a skill with its author."""
        self._skill_authors[skill_name] = author_id
        if author_id in self._authors:
            self._authors[author_id].skills_published += 1
        if skill_name not in self._stats:
            self._stats[skill_name] = SkillEconomyStats(skill_name=skill_name)

    # -- Usage tracking -----------------------------------------------------

    def record_usage(
        self,
        skill_name: str,
        user_id: str,
        success: bool = True,
        duration: float = 0.0,
    ) -> None:
        """Record a skill usage event. Awards credits to the author."""
        record = UsageRecord(
            skill_name=skill_name,
            user_id=user_id,
            success=success,
            duration_seconds=duration,
        )

        if skill_name not in self._usage:
            self._usage[skill_name] = []
        self._usage[skill_name].append(record)

        # Update stats
        stats = self._stats.setdefault(
            skill_name, SkillEconomyStats(skill_name=skill_name)
        )
        stats.total_uses += 1
        if success:
            stats.successful_uses += 1

        # Count unique users
        unique = {r.user_id for r in self._usage[skill_name]}
        stats.unique_users = len(unique)

        # Update trend score (recent uses weighted higher)
        stats.trend_score = self._compute_trend(skill_name)

        # Award credits to author
        author_id = self._skill_authors.get(skill_name)
        if author_id and author_id in self._authors:
            credit = self.CREDITS_PER_USE if success else self.CREDITS_PER_USE * 0.25
            self._authors[author_id].credits += credit
            self._authors[author_id].total_earnings += credit
            stats.credits_earned += credit

        self._save()

    def record_install(self, skill_name: str) -> None:
        """Record a skill installation. Awards bonus credits."""
        author_id = self._skill_authors.get(skill_name)
        if author_id and author_id in self._authors:
            self._authors[author_id].credits += self.CREDITS_PER_INSTALL
            self._authors[author_id].total_earnings += self.CREDITS_PER_INSTALL
            self._authors[author_id].total_installs += 1
        self._save()

    # -- Ratings ------------------------------------------------------------

    def rate_skill(
        self,
        skill_name: str,
        rater_id: str,
        score: float,
        review: str = "",
    ) -> SkillRating:
        """Rate a skill (1.0 - 5.0 scale)."""
        score = max(1.0, min(5.0, score))

        rating = SkillRating(
            skill_name=skill_name,
            rater_id=rater_id,
            score=score,
            review=review,
        )

        if skill_name not in self._ratings:
            self._ratings[skill_name] = []

        # Replace existing rating from same rater
        self._ratings[skill_name] = [
            r for r in self._ratings[skill_name] if r.rater_id != rater_id
        ]
        self._ratings[skill_name].append(rating)

        # Update stats
        stats = self._stats.setdefault(
            skill_name, SkillEconomyStats(skill_name=skill_name)
        )
        all_scores = [r.score for r in self._ratings[skill_name]]
        stats.average_rating = sum(all_scores) / len(all_scores)
        stats.total_ratings = len(all_scores)

        # Update author average
        author_id = self._skill_authors.get(skill_name)
        if author_id and author_id in self._authors:
            self._update_author_rating(author_id)

        self._save()
        return rating

    def get_ratings(self, skill_name: str) -> list[SkillRating]:
        """Get all ratings for a skill."""
        return self._ratings.get(skill_name, [])

    # -- Analytics ----------------------------------------------------------

    def get_skill_stats(self, skill_name: str) -> SkillEconomyStats | None:
        return self._stats.get(skill_name)

    def get_trending(self, limit: int = 10) -> list[SkillEconomyStats]:
        """Get the most trending skills (recent popularity)."""
        all_stats = list(self._stats.values())
        all_stats.sort(key=lambda s: s.trend_score, reverse=True)
        return all_stats[:limit]

    def get_top_rated(self, limit: int = 10) -> list[SkillEconomyStats]:
        """Get the highest rated skills (minimum 3 ratings)."""
        qualified = [s for s in self._stats.values() if s.total_ratings >= 3]
        qualified.sort(key=lambda s: s.average_rating, reverse=True)
        return qualified[:limit]

    def get_most_used(self, limit: int = 10) -> list[SkillEconomyStats]:
        """Get the most used skills."""
        all_stats = list(self._stats.values())
        all_stats.sort(key=lambda s: s.total_uses, reverse=True)
        return all_stats[:limit]

    def get_author_leaderboard(self, limit: int = 10) -> list[AuthorProfile]:
        """Get top authors by reputation score."""
        authors = list(self._authors.values())
        authors.sort(key=lambda a: a.reputation_score, reverse=True)
        return authors[:limit]

    def get_economy_summary(self) -> dict[str, Any]:
        """Get overall economy statistics."""
        total_uses = sum(s.total_uses for s in self._stats.values())
        total_credits = sum(a.total_earnings for a in self._authors.values())
        total_ratings = sum(s.total_ratings for s in self._stats.values())

        return {
            "total_skills": len(self._stats),
            "total_authors": len(self._authors),
            "total_uses": total_uses,
            "total_credits_distributed": round(total_credits, 2),
            "total_ratings": total_ratings,
            "trending": [
                {"name": s.skill_name, "score": round(s.trend_score, 2)}
                for s in self.get_trending(5)
            ],
        }

    # -- Internal -----------------------------------------------------------

    def _compute_trend(self, skill_name: str) -> float:
        """Compute trend score based on recent usage within the window."""
        records = self._usage.get(skill_name, [])
        now = time.time()
        cutoff = now - self.TREND_WINDOW

        recent = [r for r in records if r.timestamp > cutoff]
        if not recent:
            return 0.0

        # Weight recent uses more heavily
        score = 0.0
        for r in recent:
            age_days = (now - r.timestamp) / 86400
            weight = self.TREND_DECAY ** age_days
            score += weight * (1.0 if r.success else 0.5)

        return round(score, 2)

    def _update_author_rating(self, author_id: str) -> None:
        """Recalculate an author's average rating across all their skills."""
        author = self._authors.get(author_id)
        if not author:
            return

        all_ratings = []
        for skill, aid in self._skill_authors.items():
            if aid == author_id and skill in self._ratings:
                all_ratings.extend(r.score for r in self._ratings[skill])

        if all_ratings:
            author.average_rating = sum(all_ratings) / len(all_ratings)

    def _save(self) -> None:
        """Persist economy state to disk."""
        state = {
            "authors": {
                k: {
                    "author_id": v.author_id,
                    "display_name": v.display_name,
                    "credits": v.credits,
                    "total_earnings": v.total_earnings,
                    "skills_published": v.skills_published,
                    "total_installs": v.total_installs,
                    "average_rating": v.average_rating,
                    "joined_at": v.joined_at,
                }
                for k, v in self._authors.items()
            },
            "skill_authors": self._skill_authors,
            "stats": {
                k: {
                    "skill_name": v.skill_name,
                    "total_uses": v.total_uses,
                    "successful_uses": v.successful_uses,
                    "unique_users": v.unique_users,
                    "average_rating": v.average_rating,
                    "total_ratings": v.total_ratings,
                    "credits_earned": v.credits_earned,
                    "trend_score": v.trend_score,
                }
                for k, v in self._stats.items()
            },
        }
        path = self._data_dir / "economy_state.json"
        path.write_text(json.dumps(state, indent=2))

    def _load(self) -> None:
        """Load economy state from disk."""
        path = self._data_dir / "economy_state.json"
        if not path.exists():
            return

        try:
            state = json.loads(path.read_text())

            for k, v in state.get("authors", {}).items():
                self._authors[k] = AuthorProfile(**v)

            self._skill_authors = state.get("skill_authors", {})

            for k, v in state.get("stats", {}).items():
                self._stats[k] = SkillEconomyStats(**v)
        except Exception:
            pass  # Start fresh if state is corrupted
