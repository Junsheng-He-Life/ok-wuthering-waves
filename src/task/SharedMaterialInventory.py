"""Account once for each named inventory item across all cultivation targets."""
from collections import defaultdict


def summarize_shared_inventory(items, recipes=()):
    """Combine requirements first, then craft only from unreserved surplus.

    Each recipe is (source_name, target_name, ratio). This computes a plan;
    it does not execute synthesis or assert that a recipe is unlocked.
    Conflicting or missing inventory observations remain unresolved.
    """
    demands = defaultdict(int)
    roles = defaultdict(lambda: defaultdict(int))
    observations = defaultdict(set)
    for row in items:
        name = row.get('item_name')
        if not name:
            continue
        need = int(row['required'])
        demands[name] += need
        roles[name][row['target']] += need
        if row.get('inventory') is not None:
            observations[name].add(int(row['inventory']))
    stock = {name: next(iter(observations[name])) for name in demands
             if len(observations[name]) == 1}
    original = dict(stock)
    by_target = {}
    for source, target, ratio in recipes:
        if ratio < 2 or source == target or target in by_target:
            raise ValueError('invalid or duplicate synthesis recipe')
        by_target[target] = (source, ratio)
    crafted = defaultdict(int)
    used = defaultdict(int)
    visiting = set()
    def supply(name, amount):
        if name in visiting:
            raise ValueError('cyclic synthesis recipes')
        if name not in stock or stock[name] >= amount or name not in by_target:
            return
        source, ratio = by_target[name]
        if source not in stock:
            return
        visiting.add(name)
        short = amount - stock[name]
        supply(source, demands.get(source, 0) + short * ratio)
        made = min(short, max(0, stock[source] - demands.get(source, 0)) // ratio)
        stock[source] -= made * ratio
        stock[name] += made
        crafted[name] += made
        used[source] += made * ratio
        visiting.remove(name)
    # Recursion reserves every lower tier's full combined demand before any
    # upward conversion, independent of the order roles were scanned.
    for name in sorted(demands):
        supply(name, demands[name])
    result = []
    for name in sorted(demands):
        inventory = original.get(name)
        result.append({'item_name': name, 'inventory': inventory,
            'inventory_conflict': len(observations[name]) > 1,
            'inventory_observations': sorted(observations[name]),
            'required_total': demands[name], 'by_target': dict(roles[name]),
            'raw_missing': None if inventory is None else max(0, demands[name]-inventory),
            'craft_output': crafted[name], 'craft_input': used[name],
            'projected_inventory': stock.get(name),
            'missing_after_synthesis': None if name not in stock else max(0, demands[name]-stock[name])})
    return result
