"""One explicit cultivation scope shared by all requested characters."""

CULTIVATION_KINDS = ('声骸', '突破', '武器/技能', '周本', '角色经验', '武器经验', '贝币')


def cultivation_kinds(value):
    """Reject empty/unknown scopes rather than falling back to all materials."""
    items = value.split(',') if isinstance(value, str) else list(value)
    if not items or any(item not in CULTIVATION_KINDS for item in items):
        raise ValueError('请至少选择一个有效的刷取项目。')
    if len(set(items)) != len(items):
        raise ValueError('刷取项目不能重复。')
    return tuple(kind for kind in CULTIVATION_KINDS if kind in items)


def recommended_echo_locations(locations, *, verified_set=None):
    """Accept repeated Tacet rows only after a live named Sonata filter.

    The caller must first read the character's Sonata name in the cultivation
    panel and verify that exact name in the Tacet filter header.
    This deliberately does not expand by material-icon similarity: Tacet
    previews share generic icons even when their Sonata sets differ. A Boss
    ascension-material marker is also not evidence of a suitable Echo set.
    """
    if not verified_set:
        return []
    return [row for row in locations
            if row.get('observation_count', 0) >= 2
            and row.get('name') and row.get('normalized_name')
            and not row['normalized_name'].startswith('row-')]
