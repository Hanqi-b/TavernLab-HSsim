import { asArray, safeNumber, snapshotFingerprint } from "./gui_utils.js";

function emptySelection() {
  return {
    type: null,
    sourceId: null,
    branchId: null,
    targetId: null,
    position: null,
    mulliganIds: [],
  };
}

function freezeSnapshot(value, seen = new WeakSet()) {
  if (!value || typeof value !== "object" || seen.has(value)) return value;
  seen.add(value);
  if (value instanceof Map) {
    value.forEach((entry) => freezeSnapshot(entry, seen));
  } else {
    Object.values(value).forEach((entry) => freezeSnapshot(entry, seen));
  }
  return Object.freeze(value);
}

function readonlyMap(map) {
  return Object.freeze({
    get(key) { return map.get(key); },
    keys() { return map.keys(); },
  });
}

function freezeActionIndex(indexed) {
  [indexed.actions, indexed.mulligan, indexed.choices, indexed.endTurn].forEach((value) => Object.freeze(value));
  [indexed.byType, indexed.bySource, indexed.byTarget].forEach((map) => {
    if (map) map.forEach((value) => Object.freeze(value));
  });
  indexed.byType = readonlyMap(indexed.byType);
  indexed.bySource = readonlyMap(indexed.bySource);
  indexed.byTarget = readonlyMap(indexed.byTarget);
  return Object.freeze(indexed);
}

/**
 * Match state is private to this store. Consumers get a snapshot view and
 * use transition methods instead of mutating nested fields.
 */
export function createGuiState(model) {
  const current = {
    snapshot: null,
    actionIndex: freezeActionIndex(model.index([])),
    selection: emptySelection(),
    fingerprint: "",
    latestEventSeq: null,
    outcomeDismissedRevision: null,
  };

  function isDecisionChanged(next) {
    return !current.snapshot ||
      next.session_id !== current.snapshot.session_id ||
      next.revision !== current.snapshot.revision;
  }

  function isStale(next) {
    return Boolean(current.snapshot &&
      next.session_id === current.snapshot.session_id &&
      next.revision < current.snapshot.revision);
  }

  function selectionCriteria(value) {
    const criteria = {};
    if (value.type) criteria.type = value.type;
    if (value.sourceId !== null) criteria.source_entity_id = value.sourceId;
    if (value.branchId !== null) criteria.choose_option_entity_id = value.branchId;
    if (value.targetId !== null) criteria.target_entity_id = value.targetId;
    if (value.position !== null) criteria.position = value.position;
    return criteria;
  }

  function hasSelection(value) {
    return Boolean(value.type) || value.sourceId !== null ||
      value.branchId !== null || value.targetId !== null ||
      value.position !== null || value.mulliganIds.length > 0;
  }

  function cloneSelection(value = emptySelection()) {
    return {
      type: value.type || null,
      sourceId: value.sourceId === undefined ? null : value.sourceId,
      branchId: value.branchId === undefined ? null : value.branchId,
      targetId: value.targetId === undefined ? null : value.targetId,
      position: value.position === undefined ? null : value.position,
      mulliganIds: asArray(value.mulliganIds).slice(),
    };
  }

  function selectionIsValid(value, indexed) {
    if (!hasSelection(value)) return true;
    if (value.type === "MULLIGAN" || value.mulliganIds.length) {
      return Boolean(model.findMulligan(indexed, value.mulliganIds));
    }
    return model.filter(indexed.actions, selectionCriteria(value)).length > 0;
  }

  function view() {
    return {
      snapshot: current.snapshot,
      actionIndex: current.actionIndex,
      selection: cloneSelection(current.selection),
      fingerprint: current.fingerprint,
      latestEventSeq: current.latestEventSeq,
      outcomeDismissedRevision: current.outcomeDismissedRevision,
    };
  }

  return {
    get current() { return view(); },
    isDecisionChanged,
    isStale,
    selectedActions() {
      return model.filter(current.actionIndex.actions, selectionCriteria(current.selection));
    },
    resetSelection() {
      current.selection = emptySelection();
      return cloneSelection(current.selection);
    },
    updateSelection(mutator) {
      const next = cloneSelection(current.selection);
      if (typeof mutator === "function") mutator(next);
      current.selection = next;
      return cloneSelection(next);
    },
    resetMatch() {
      current.snapshot = null;
      current.actionIndex = freezeActionIndex(model.index([]));
      current.selection = emptySelection();
      current.fingerprint = "";
      current.latestEventSeq = null;
      current.outcomeDismissedRevision = null;
    },
    dismissOutcome() {
      current.outcomeDismissedRevision = current.snapshot ? current.snapshot.revision : null;
    },
    commit(next, options) {
      const previous = current.snapshot;
      let previousEventSeq = current.latestEventSeq;
      const sessionChanged = Boolean(previous && previous.session_id !== next.session_id);
      let resetSelection = Boolean(options && options.resetSelection) || sessionChanged || isDecisionChanged(next);
      const indexed = model.index(next.legal_actions);
      if (resetSelection || !selectionIsValid(current.selection, indexed)) {
        current.selection = emptySelection();
        resetSelection = true;
      } else {
        current.selection = cloneSelection(current.selection);
      }
      current.snapshot = freezeSnapshot(next);
      current.actionIndex = freezeActionIndex(indexed);
      current.fingerprint = snapshotFingerprint(next);
      const events = asArray(next.events);
      const newest = events.length ? events[events.length - 1] : null;
      const newestSeq = safeNumber(newest && newest.seq, previousEventSeq);
      if (sessionChanged) {
        current.latestEventSeq = null;
        current.outcomeDismissedRevision = null;
        previousEventSeq = null;
      }
      if (events.length) current.latestEventSeq = newestSeq;
      return { previous, previousEventSeq, newest, newestSeq, events, resetSelection, sessionChanged };
    },
  };
}

export { emptySelection };
