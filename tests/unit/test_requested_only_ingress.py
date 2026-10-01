"""The product has no unattended ingress or scheduled quota allocation."""

from ignis.domain.value_objects import IngressTrigger
from ignis.domain.youtube_quota import YouTubeQuotaPolicy


def test_ingress_trigger_exposes_only_explicit_requests():
    assert list(IngressTrigger) == [IngressTrigger.REQUESTED]
    assert "scheduled" not in IngressTrigger._value2member_map_


def test_youtube_quota_policy_has_no_scheduled_allocation():
    policy = YouTubeQuotaPolicy(search_daily_limit=100)
    assert not hasattr(policy, "scheduled_search_daily_limit")
    assert not hasattr(policy, "scheduled_limit")
