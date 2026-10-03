#!/usr/bin/env python3
"""Compare versioned MCTS tactics through complete real-engine turns.

Run from a source checkout with its development dependencies installed.
Turn wall times include assertions/GC; ai_decision_seconds measures only
choose_action calls, including isolated root construction.
"""
import argparse
import gc
import json
import logging
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hearthstone.enums import CardClass, Zone
from fireplace.exceptions import GameOver
from fireplace.mcts_agent import MCTSAgent
from fireplace.replay_state import normalized_game_state
from tests.test_search_simulation import main_session

# Fireplace's fixture helpers install a DEBUG stream handler; keep benchmark
# progress readable and prevent logging overhead from dominating the runs.
logging.getLogger('fireplace').setLevel(logging.CRITICAL)

OUT = Path('/tmp/tavernlab-mcts-tactical-benchmark.json')
SEEDS = range(8)
LIMIT = 16
CASES = [
    'two_face_lethal', 'crowded_face_lethal', 'spell_combo_lethal',
    'taunt_then_lethal', 'remove_one_yeti_to_survive', 'frostbolt_choice',
]
LETHAL_CASES = frozenset(CASES[:4])
CONFIGS = [
    ('legacy_timed', 'legacy_v1', 0.2),
    ('legacy_128', 'legacy_v1', None),
    ('tactical_v2', 'tactical_v2', 0.2),
]

def setup(case):
    session, p = main_session()
    e = p.opponent
    p.temp_mana = 0
    p.max_mana = {'two_face_lethal': 0, 'crowded_face_lethal': 0,
                  'spell_combo_lethal': 6, 'taunt_then_lethal': 0,
                  'remove_one_yeti_to_survive': 4, 'frostbolt_choice': 2}[case]
    p.used_mana = 0
    meta = {'own_minions': [], 'enemy_minions': [], 'spells': []}
    if case in ('two_face_lethal', 'crowded_face_lethal', 'taunt_then_lethal'):
        for _ in range(2):
            m = p.summon('CS2_179')
            m.turns_in_play = 1
            meta['own_minions'].append(m.entity_id)
    if case == 'two_face_lethal':
        w = e.summon('CS2_231')
        meta['enemy_minions'].append(w.entity_id)
        e.hero.damage = e.hero.max_health - 6
    elif case == 'crowded_face_lethal':
        for _ in range(7):
            w = e.summon('CS2_231')
            meta['enemy_minions'].append(w.entity_id)
        e.hero.damage = e.hero.max_health - 6
    elif case == 'spell_combo_lethal':
        for cid in ('CS2_029', 'CS2_024'):
            spell = p.card(cid, zone=Zone.HAND)
            meta['spells'].append(spell.entity_id)
        for _ in range(3):
            w = e.summon('CS2_231')
            meta['enemy_minions'].append(w.entity_id)
        e.hero.damage = e.hero.max_health - 9
    elif case == 'taunt_then_lethal':
        t = e.summon('CS1_042')
        t.turns_in_play = 1
        meta['taunt'] = t.entity_id
        meta['enemy_minions'].append(t.entity_id)
        for _ in range(4):
            w = e.summon('CS2_231')
            meta['enemy_minions'].append(w.entity_id)
        e.hero.damage = e.hero.max_health - 3
    elif case == 'remove_one_yeti_to_survive':
        p.hero.damage = p.hero.max_health - 6
        yetis = []
        for _ in range(2):
            m = e.summon('CS2_182')
            m.turns_in_play = 1
            yetis.append(m.entity_id)
        meta['enemy_minions'] = yetis
        spell = p.card('CS2_029', zone=Zone.HAND)
        meta['spells'] = [spell.entity_id]
    elif case == 'frostbolt_choice':
        spell = p.card('CS2_024', zone=Zone.HAND)
        meta['spells'] = [spell.entity_id]
        raptor = e.summon('CS2_172')
        raptor.turns_in_play = 1
        meta['raptor'] = raptor.entity_id
        meta['enemy_minions'] = [raptor.entity_id]
    return session, p, meta

def card_name(obj):
    if obj is None:
        return 'unknown'
    return str(getattr(obj, 'name', None) or getattr(obj, 'id', 'unknown'))

def action_desc(session, p, action):
    get = session.index.get
    src = get(action.source_entity_id) if action.source_entity_id else None
    tgt = get(action.target_entity_id) if action.target_entity_id else None
    if action.type == 'END_TURN':
        return 'End turn'
    if action.type == 'ATTACK':
        return f'{card_name(src)} attacks {target_desc(tgt, p)}'
    if action.type == 'PLAY_CARD':
        return f'Play {card_name(src)}' + (f' -> {target_desc(tgt, p)}' if tgt else '')
    if action.type == 'USE_HERO_POWER':
        return f'Use {card_name(src)}' + (f' -> {target_desc(tgt, p)}' if tgt else '')
    return action.type

def target_desc(obj, p):
    if obj is None:
        return 'no target'
    if obj is p.hero:
        return 'own hero'
    if obj is p.opponent.hero:
        return 'enemy hero'
    side = 'own' if getattr(obj, 'controller', None) is p else 'enemy'
    return f'{side} {card_name(obj)}#{obj.entity_id}'

def find_action(session, p, kind, source=None, target=None):
    for a in session.legal_actions(p):
        if a.type == kind and (source is None or a.source_entity_id == source) \
                and (target is None or a.target_entity_id == target):
            return a
    raise AssertionError(f'No legal {kind} action source={source} target={target}')

def play_card(session, p, source, target=None):
    a = find_action(session, p, 'PLAY_CARD', source, target)
    try:
        session.execute(p, a)
    except GameOver:
        pass

def attack(session, p, source, target):
    a = find_action(session, p, 'ATTACK', source, target)
    try:
        session.execute(p, a)
    except GameOver:
        pass

def prove_fixtures():
    """Check forced lines directly through Fireplace before measuring agents."""
    proof = {}
    for case in CASES[:2]:
        s, p, m = setup(case)
        for source in m['own_minions']:
            attack(s, p, source, p.opponent.hero.entity_id)
        assert s.game.ended and p.opponent.hero.health <= 0 and p.hero.health > 0
        proof[case] = {'line': 'both ready Sen\'jin attack enemy hero', 'terminal_win': True}
        s.close()
    s, p, m = setup('spell_combo_lethal')
    # Frostbolt first, Fireball second: 3 + 6 damage for six mana.
    fire = next(c.entity_id for c in p.hand if c.id == 'CS2_029')
    frost = next(c.entity_id for c in p.hand if c.id == 'CS2_024')
    play_card(s, p, frost, p.opponent.hero.entity_id)
    play_card(s, p, fire, p.opponent.hero.entity_id)
    assert s.game.ended and p.opponent.hero.health <= 0 and p.hero.health > 0
    proof['spell_combo_lethal'] = {'line': 'Frostbolt enemy hero, Fireball enemy hero', 'terminal_win': True}
    s.close()
    s, p, m = setup('taunt_then_lethal')
    attack(s, p, m['own_minions'][0], m['taunt'])
    assert all(x.entity_id != m['taunt'] for x in p.opponent.field)
    attack(s, p, m['own_minions'][1], p.opponent.hero.entity_id)
    assert s.game.ended and p.opponent.hero.health <= 0 and p.hero.health > 0
    proof['taunt_then_lethal'] = {'line': 'kill Goldshire Footman with first attack, second attacks face', 'terminal_win': True}
    s.close()
    s, p, m = setup('remove_one_yeti_to_survive')
    play_card(s, p, m['spells'][0], m['enemy_minions'][0])
    end = find_action(s, p, 'END_TURN')
    s.execute(p, end)
    remaining = sum(max(0, int(x.atk)) for x in p.opponent.field if x.can_attack())
    assert s.game.current_player is p.opponent and remaining < p.hero.health
    proof['remove_one_yeti_to_survive'] = {'line': 'Fireball one Yeti, end turn', 'enemy_attack': remaining, 'own_health': p.hero.health, 'survives_visible_attack': True}
    s.close()
    s, p, m = setup('frostbolt_choice')
    play_card(s, p, m['spells'][0], m['raptor'])
    assert all(x.entity_id != m['raptor'] for x in p.opponent.field)
    proof['frostbolt_choice'] = {'line': 'Frostbolt Raptor', 'raptor_removed': True}
    s.close()
    return proof

def visible_attack(p):
    return sum(max(0, int(m.atk)) for m in p.opponent.field if m.can_attack())

def run_one(case, config_name, policy_version, budget, seed):
    session, p, meta = setup(case)
    agent = MCTSAgent(seed=seed, policy_version=policy_version, time_budget=budget, max_iterations=128, max_depth=12)
    start_turn = time.perf_counter()
    records = []
    reason = 'action_cap'
    for i in range(LIMIT):
        if session.game.ended:
            reason = 'terminal'
            break
        if session.game.current_player is not p:
            reason = 'player_changed'
            break
        before = normalized_game_state(session.game)
        rng = session.game.random.getstate()
        legal = session.legal_actions(p)
        t0 = time.perf_counter()
        action = session.choose_action(p, agent=agent)
        elapsed = time.perf_counter() - t0
        assert action in legal, f'chosen action not legal: {action!r}'
        assert normalized_game_state(session.game) == before, 'choose_action mutated normalized game state'
        assert session.game.random.getstate() == rng, 'choose_action mutated live RNG'
        stats = dict(agent.last_search_stats)
        records.append({
            'index': i + 1, 'action': action.to_dict(),
            'description': action_desc(session, p, action), 'legal_action_count': len(legal),
            'decision_wall_seconds': elapsed,
            'search': {k: stats.get(k) for k in ('iterations', 'mode', 'completed_leaves', 'truncated_lines', 'best_score', 'elapsed', 'failed_lines', 'policy_version', 'time_budget', 'deterministic_lethal', 'tactical_nodes', 'tactical_failed_lines', 'uncertain_lines', 'reply_nodes')},
        })
        gc.collect()  # outside the measured choose_action interval
        try:
            session.execute(p, action)
        except GameOver:
            reason = 'terminal'
            break
        if session.game.ended:
            reason = 'terminal'
            break
        if session.game.current_player is not p:
            reason = 'player_changed'
            break
    else:
        reason = 'action_cap'
    turn_elapsed = time.perf_counter() - start_turn
    result = {
        'case': case, 'config': config_name, 'seed': seed, 'stop_reason': reason,
        'agent_config': {'policy_version': agent.policy_version, **agent.export_config()},
        'action_count': len(records), 'turn_wall_seconds': turn_elapsed,
        'ai_decision_seconds': sum(d['decision_wall_seconds'] for d in records),
        'decisions': records,
        'final': {'game_ended': session.game.ended, 'own_hero_health': int(p.hero.health),
                  'enemy_hero_health': int(p.opponent.hero.health), 'own_mana': int(p.mana),
                  'enemy_visible_next_attack': visible_attack(p) if session.game.current_player is p.opponent else None},
    }
    if case in LETHAL_CASES:
        result['full_turn_lethal_success'] = bool(reason == 'terminal' and session.game.ended and p.opponent.hero.health <= 0 and p.hero.health > 0)
    elif case == 'remove_one_yeti_to_survive':
        total = result['final']['enemy_visible_next_attack']
        result['survived_visible_attack_at_turn_end'] = bool(reason == 'player_changed' and total is not None and total < p.hero.health)
        result['enemy_minions_remaining'] = [x.id for x in p.opponent.field]
    else:
        raptor = session.index.get(meta['raptor'])
        result['raptor_removed_or_frozen'] = bool(raptor not in p.opponent.field or getattr(raptor, 'frozen', False))
        result['face_used'] = any(a['action'].get('target_entity_id') == p.opponent.hero.entity_id for a in records)
        result['leftover_mana'] = int(p.mana)
    session.close()
    return result

def summarize(results):
    out = {}
    for case in CASES:
        out[case] = {}
        for config, _, _ in CONFIGS:
            rows = [r for r in results if r.get('case') == case and r.get('config') == config]
            times = [d['decision_wall_seconds'] for r in rows for d in r.get('decisions', [])]
            turns = [r['turn_wall_seconds'] for r in rows if 'turn_wall_seconds' in r]
            iters = [d['search']['iterations'] for r in rows for d in r.get('decisions', []) if d['search']['iterations'] is not None]
            item = {
                'completed_runs': len(rows), 'requested_runs': len(SEEDS), 'failed_runs': sum('error' in r for r in rows),
                'decision_seconds_mean': statistics.mean(times) if times else None,
                'decision_seconds_median': statistics.median(times) if times else None,
                'turn_seconds_mean': statistics.mean(turns) if turns else None,
                'turn_seconds_median': statistics.median(turns) if turns else None,
                'ai_turn_seconds_mean': statistics.mean(r['ai_decision_seconds'] for r in rows if 'ai_decision_seconds' in r) if turns else None,
                'search_modes': sorted({d['search']['mode'] for r in rows for d in r.get('decisions', [])}),
                'actual_iterations_min': min(iters) if iters else None,
                'actual_iterations_max': max(iters) if iters else None,
                'actual_iterations_per_decision': iters,
                'stop_reasons': {reason: sum(r.get('stop_reason') == reason for r in rows) for reason in ('terminal', 'player_changed', 'action_cap')},
            }
            if case in LETHAL_CASES:
                item['lethal_successes'] = sum(r.get('full_turn_lethal_success') is True for r in rows)
            elif case == 'remove_one_yeti_to_survive':
                item['safe_turn_ends'] = sum(r.get('survived_visible_attack_at_turn_end') is True for r in rows)
                item['visible_attack_by_run'] = [r.get('final', {}).get('enemy_visible_next_attack') for r in rows]
            else:
                item['raptor_control'] = sum(r.get('raptor_removed_or_frozen') is True for r in rows)
                item['face_used'] = sum(r.get('face_used') is True for r in rows)
                item['leftover_mana_by_run'] = [r.get('leftover_mana') for r in rows]
            out[case][config] = item
    return out

def main():
    global OUT, SEEDS, CASES, CONFIGS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--cases', nargs='+', choices=CASES)
    parser.add_argument('--configs', nargs='+', choices=[c[0] for c in CONFIGS])
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error('--seeds must be positive')
    OUT, SEEDS = args.output, range(args.seeds)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Verify every fixture before optionally selecting a smaller sweep.
    proofs = prove_fixtures()
    if args.cases:
        CASES = args.cases
    if args.configs:
        CONFIGS = [c for c in CONFIGS if c[0] in args.configs]
    print('Fixture proofs passed through real Fireplace actions.', flush=True)
    results = []
    for case in CASES:
        print(f'Starting {case}', flush=True)
        for seed in SEEDS:
            for config_name, policy_version, budget in CONFIGS:
                try:
                    result = run_one(case, config_name, policy_version, budget, seed)
                except Exception as exc:
                    result = {'case': case, 'config': config_name, 'seed': seed,
                              'error': repr(exc), 'traceback': traceback.format_exc()}
                    results.append(result)
                    print(f'FAILED {case} {config_name} seed={seed}: {exc!r}', flush=True)
                else:
                    results.append(result)
                    print(f"Done {case} {config_name} seed={seed}: {result['stop_reason']}, {result['action_count']} actions, AI={result['ai_decision_seconds']:.3f}s", flush=True)
                payload = {'proofs': proofs, 'seed_count': len(SEEDS), 'results': results, 'summary': summarize(results)}
                OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        print(f'Completed scenario {case}', flush=True)
    failures = [r for r in results if 'error' in r]
    print(f'JSON: {OUT}; runs={len(results)}; failures={len(failures)}', flush=True)
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
