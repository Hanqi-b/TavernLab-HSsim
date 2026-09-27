export function createDecisions(deps) {
  "use strict";
  const {
    document, elements, state, model, data, dom, locale, cards,
    onRender, onSubmitAction, onLoadState, getBusy,
  } = deps;

  function selectedActions() {
    return state.selectedActions();
  }

  function chooseSource(type, sourceId) {
    if (getBusy() || !state.current.snapshot) {
      return;
    }
    state.resetSelection();
    state.updateSelection(function (selection) {
      selection.type = type;
      selection.sourceId = sourceId;
    });
    onRender();
    maybeSubmitSingle();
  }

  function chooseBranch(branchId) {
    state.updateSelection(function (selection) {
      selection.branchId = branchId;
      selection.targetId = null;
      selection.position = null;
    });
    onRender();
    maybeSubmitSingle();
  }

  function chooseTarget(targetIdValue) {
    var id = data.entityId(targetIdValue);
    if (id === null || !targetIds().has(id)) {
      return false;
    }
    state.updateSelection(function (selection) {
      selection.targetId = id;
    });
    onRender();
    maybeSubmitSingle();
    return true;
  }

  function choosePosition(position) {
    if (!model.uniqueValues(selectedActions(), "position").some(function (value) { return value === position; })) {
      return;
    }
    state.updateSelection(function (selection) {
      selection.position = position;
    });
    onRender();
    maybeSubmitSingle();
  }

  function maybeSubmitSingle() {
    var candidates = selectedActions();
    if (candidates.length !== 1) {
      return;
    }
    var action = candidates[0];
    if (!actionRequiresSelection(action)) {
      submitRawAction(action);
    }
  }

  function actionRequiresSelection(action) {
    var selection = state.current.selection;
    return data.isObject(action) && (
      (action.choose_option_entity_id !== undefined && selection.branchId === null) ||
      (action.target_entity_id !== undefined && selection.targetId === null) ||
      (action.position !== undefined && selection.position === null)
    );
  }

  function toggleMulligan(id) {
    if (id === null || !state.current.snapshot) {
      return;
    }
    var selection = state.current.selection;
    var next = selection.mulliganIds.slice();
    var index = next.indexOf(id);
    if (index >= 0) {
      next.splice(index, 1);
    } else {
      next.push(id);
    }
    state.updateSelection(function (nextSelection) {
      nextSelection.mulliganIds = next;
    });
    onRender();
  }

  function cancelSelection() {
    state.resetSelection();
    onRender();
  }

  function submitSelected() {
    var snapshot = state.current.snapshot;
    var actionIndex = state.current.actionIndex;
    var selection = state.current.selection;
    if (!snapshot || getBusy()) {
      return;
    }
    if (snapshot.observation.phase === "MULLIGAN") {
      var mulligan = model.findMulligan(actionIndex, selection.mulliganIds);
      if (mulligan) {
        submitRawAction(mulligan);
      } else {
        dom.showNotice(locale.tr("oldAction"), "error", 3600);
      }
      return;
    }
    var candidates = selectedActions();
    if (candidates.length === 1 && !actionRequiresSelection(candidates[0])) {
      submitRawAction(candidates[0]);
    } else {
      dom.showNotice(locale.tr("selectionRequired"), "error", 2800);
    }
  }

  function submitEndTurn() {
    var actionIndex = state.current.actionIndex;
    if (actionIndex.endTurn.length === 1) {
      submitRawAction(actionIndex.endTurn[0]);
    }
  }

  function actionIndexOf(action) {
    var actionIndex = state.current.actionIndex;
    var direct = actionIndex.actions.indexOf(action);
    if (direct >= 0) {
      return direct;
    }
    var key = model.actionKey(action);
    for (var index = 0; index < actionIndex.actions.length; index += 1) {
      if (model.actionKey(actionIndex.actions[index]) === key) {
        return index;
      }
    }
    return -1;
  }

  function submitRawAction(action) {
    var index = actionIndexOf(action);
    if (index < 0) {
      dom.showNotice(locale.tr("oldAction"), "error", 3600);
      onLoadState(false);
      return;
    }
    onSubmitAction(index);
  }

  function renderDecision() {
    var snapshot = state.current.snapshot;
    var actionIndex = state.current.actionIndex;
    var selection = state.current.selection;
    dom.clear(elements["quick-actions"]);
    dom.setHidden(elements["quick-actions"], true);
    dom.clear(elements["choice-options"]);
    dom.clear(elements["position-choices"]);
    dom.clear(elements["pending-choice"]);
    dom.setHidden(elements["pending-choice"], true);
    dom.setHidden(elements["selection-summary"], true);
    dom.setHidden(elements["action-instructions"], false);
    dom.setHidden(elements["target-hint"], true);
    dom.setHidden(elements["action-submit"], true);
    dom.setHidden(elements["selection-cancel"], true);
    dom.setHidden(elements["end-turn-button"], true);
    var phase = snapshot && snapshot.observation ? data.safeText(snapshot.observation.phase, "") : "";
    elements["decision-panel"].classList.toggle("phase-choice", phase === "CHOICE");
    elements["decision-panel"].classList.toggle("phase-mulligan", phase === "MULLIGAN");
    if (!snapshot) {
      dom.setText(elements["action-instructions"], locale.tr("loadingMatch"));
      return;
    }
    if (phase === "GAME_OVER") {
      dom.setText(elements["action-instructions"], locale.tr("gameOverInstruction"));
      return;
    }
    if (phase === "MULLIGAN") {
      dom.setText(elements["action-instructions"], locale.tr("mulliganInstruction"));
      renderPendingChoice(snapshot.observation.pending_choice);
      var mulliganAction = model.findMulligan(actionIndex, selection.mulliganIds);
      dom.setText(elements["action-submit"], mulliganAction ? locale.tr("confirmMulligan") : locale.tr("chooseMulligan"));
      dom.setHidden(elements["action-submit"], false);
      return;
    }
    if (phase === "CHOICE") {
      dom.setText(elements["action-instructions"], locale.tr("selectOption"));
      renderPendingChoice(snapshot.observation.pending_choice);
      renderChoiceOptions(actionIndex.choices);
      return;
    }
    if (phase !== "MAIN") {
      dom.setText(elements["action-instructions"], locale.tr("waitingOpponent"));
      return;
    }

    // Directly actionable cards and the lower backup controls make the
    // permanent help banner redundant on the battlefield.  Selection hints
    // below remain visible when the player actually needs a choice.
    dom.setHidden(elements["action-instructions"], true);

    if (actionIndex.endTurn.length === 1) {
      dom.setHidden(elements["end-turn-button"], false);
    }
    if (selection.sourceId === null) {
      renderQuickActions();
    }
    var candidates = selectedActions();
    if (selection.sourceId !== null) {
      dom.setHidden(elements["selection-cancel"], false);
      dom.setText(elements["selection-summary"], selectedSummary(candidates));
      dom.setHidden(elements["selection-summary"], false);
      renderSourceOptions(candidates);
      var targetOptions = model.uniqueValues(candidates, "target_entity_id");
      if (targetOptions.length) {
        dom.setText(elements["target-hint"], locale.tr("chooseTarget"));
        dom.setHidden(elements["target-hint"], false);
      }
      if (candidates.length === 1 && !actionRequiresSelection(candidates[0])) {
        dom.setText(elements["action-submit"], locale.tr("confirm") + " " + data.labelForType(candidates[0].type));
        dom.setHidden(elements["action-submit"], false);
      }
      if (!candidates.length) {
        dom.setText(elements["action-instructions"], locale.tr("selectionInvalid"));
      }
    } else {
      dom.setText(elements["action-instructions"], locale.tr("mainInstruction"));
    }
  }

  function renderQuickActions() {
    var actionIndex = state.current.actionIndex;
    var groups = [
      { type: "PLAY_CARD", title: locale.tr("play") },
      { type: "ATTACK", title: locale.tr("attackTarget") },
      { type: "USE_HERO_POWER", title: locale.tr("usePower") },
    ];
    groups.forEach(function (group) {
      var actions = actionIndex.byType.get(group.type) || [];
      var seen = new Set();
      var sources = [];
      actions.forEach(function (action) {
        var id = data.entityId(action.source_entity_id);
        if (id !== null && !seen.has(id)) {
          seen.add(id);
          sources.push(id);
        }
      });
      if (!sources.length) {
        return;
      }
      var section = document.createElement("section");
      section.className = "quick-action-group";
      var heading = document.createElement("h3");
      heading.className = "tool-heading";
      heading.textContent = group.title;
      section.appendChild(heading);
      var buttons = document.createElement("div");
      buttons.className = "quick-action-list";
      sources.forEach(function (id) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "quick-action-button";
        button.setAttribute("data-testid", "quick-action");
        button.setAttribute("data-action-type", group.type);
        button.setAttribute("data-source-id", String(id));
        button.textContent = group.title + " · " + labelForEntity(id) + sourceLocation(id, group.type);
        button.addEventListener("click", function () { chooseSource(group.type, id); });
        buttons.appendChild(button);
      });
      section.appendChild(buttons);
      elements["quick-actions"].appendChild(section);
    });
    dom.setHidden(elements["quick-actions"], !elements["quick-actions"].childElementCount);
  }

  function sourceLocation(id, type) {
    var snapshot = state.current.snapshot;
    var self = snapshot && snapshot.observation && snapshot.observation.self;
    if (!data.isObject(self)) {
      return "";
    }
    var zone = type === "PLAY_CARD" ? data.asArray(self.hand) : data.asArray(self.board);
    var position = zone.findIndex(function (card) { return data.entityId(card.entity_id) === id; });
    if (position >= 0) {
      return type === "PLAY_CARD"
        ? " · " + locale.tr("handPosition", { value: position + 1 })
        : " · " + locale.tr("boardPosition", { value: position + 1 });
    }
    return "";
  }

  function renderPendingChoice(choice) {
    if (!data.isObject(choice)) {
      dom.setHidden(elements["pending-choice"], true);
      return;
    }
    var bounds = [];
    if (choice.min_count !== undefined) {
      bounds.push(locale.tr("atLeast", { value: choice.min_count }));
    }
    if (choice.max_count !== undefined) {
      bounds.push(locale.tr("atMost", { value: choice.max_count }));
    }
    var text = document.createElement("span");
    text.textContent = locale.tr("currentChoice") + (bounds.length ? " (" + bounds.join(", ") + ")" : "");
    elements["pending-choice"].appendChild(text);
    dom.setHidden(elements["pending-choice"], false);
  }

  function renderChoiceOptions(actions) {
    data.asArray(actions).forEach(function (action) {
      var option = optionCard(findVisibleEntity(action.choice_entity_id), function () {
        submitRawAction(action);
      });
      if (!option) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "option-button";
        button.textContent = locale.tr("choose") + " " + labelForEntity(action.choice_entity_id);
        button.addEventListener("click", function () { submitRawAction(action); });
        elements["choice-options"].appendChild(button);
      } else {
        elements["choice-options"].appendChild(option);
      }
    });
  }

  function renderSourceOptions(candidates) {
    var selection = state.current.selection;
    var branches = model.uniqueValues(candidates, "choose_option_entity_id");
    var positions = model.uniqueValues(candidates, "position");
    if (branches.length) {
      var heading = document.createElement("p");
      heading.className = "tool-heading";
      heading.textContent = locale.tr("chooseBranch");
      elements["choice-options"].appendChild(heading);
      branches.forEach(function (branchId) {
        var card = optionCard(findVisibleEntity(branchId), function () { chooseBranch(branchId); });
        if (card) {
          elements["choice-options"].appendChild(card);
        } else {
          var button = document.createElement("button");
          button.type = "button";
          button.className = "option-button" + (selection.branchId === branchId ? " selected" : "");
          button.textContent = labelForEntity(branchId);
          button.addEventListener("click", function () { chooseBranch(branchId); });
          elements["choice-options"].appendChild(button);
        }
      });
    }
    if (positions.length && selection.position === null) {
      var positionHeading = document.createElement("p");
      positionHeading.className = "tool-heading";
      positionHeading.textContent = locale.tr("choosePosition");
      elements["position-choices"].appendChild(positionHeading);
      positions.slice().sort(function (left, right) { return left - right; }).forEach(function (position) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "position-button";
        button.textContent = positionLabel(position);
        button.setAttribute("data-position", String(position));
        button.addEventListener("click", function () { choosePosition(position); });
        elements["position-choices"].appendChild(button);
      });
    }
  }

  function optionCard(card, onSelect) {
    if (!data.isObject(card)) {
      return null;
    }
    var wrapper = cards.createEntityCard(card, "card option-card", onSelect);
    wrapper.appendChild(cards.createCardArt(card, "render"));
    var copy = document.createElement("div");
    copy.className = "card-content";
    copy.appendChild(cards.cardTitle(card));
    cards.appendCardText(copy, card);
    wrapper.appendChild(copy);
    return wrapper;
  }

  function selectedSummary(candidates) {
    var selection = state.current.selection;
    var parts = [data.labelForType(selection.type) + " · " + labelForEntity(selection.sourceId)];
    if (selection.branchId !== null) {
      parts.push(locale.tr("chooseBranch") + ": " + labelForEntity(selection.branchId));
    }
    if (selection.targetId !== null) {
      parts.push(locale.tr("target") + ": " + labelForEntity(selection.targetId));
    }
    if (selection.position !== null) {
      parts.push(locale.tr("position", { value: positionLabel(selection.position) }));
    }
    if (candidates.length > 1) {
      parts.push(locale.tr("selectionNeedsMore"));
    }
    return parts.join("　");
  }

  function positionLabel(position) {
    var value = Number(position);
    if (value === 0) {
      return locale.tr("positionLeft");
    }
    return locale.tr("positionNumber", { value: value + 1 });
  }

  function findVisibleEntity(id) {
    var snapshot = state.current.snapshot;
    var wanted = data.entityId(id);
    if (wanted === null || !snapshot) {
      return null;
    }
    var found = null;
    function visit(value) {
      if (found) {
        return;
      }
      if (Array.isArray(value)) {
        value.forEach(visit);
        return;
      }
      if (!data.isObject(value)) {
        return;
      }
      if (data.entityId(value.entity_id) === wanted && value.card_id) {
        found = value;
        return;
      }
      Object.keys(value).forEach(function (key) {
        if (!found && (Array.isArray(value[key]) || data.isObject(value[key]))) {
          visit(value[key]);
        }
      });
    }
    visit(snapshot.observation.self);
    visit(snapshot.observation.opponent);
    visit(snapshot.observation.pending_choice);
    return found;
  }

  function renderActions() {
    var snapshot = state.current.snapshot;
    var actionIndex = state.current.actionIndex;
    dom.clear(elements["action-menu"]);
    var types = model.actionTypes(actionIndex);
    if (!types.length) {
      var empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = snapshot && snapshot.outcome ? locale.tr("ended") : locale.tr("noActions");
      elements["action-menu"].appendChild(empty);
      return;
    }
    types.forEach(function (type) {
      var group = document.createElement("section");
      group.className = "action-group";
      var heading = document.createElement("div");
      heading.className = "action-group-title";
      var title = document.createElement("span");
      title.textContent = data.labelForType(type);
      heading.appendChild(title);
      var count = document.createElement("span");
      count.textContent = String(actionIndex.byType.get(type).length);
      heading.appendChild(count);
      group.appendChild(heading);
      var list = document.createElement("div");
      list.className = "action-list";
      actionIndex.byType.get(type).forEach(function (action) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "action-button";
        button.setAttribute("data-action-type", data.safeText(action.type, "UNKNOWN"));
        button.setAttribute("data-action-key", model.actionKey(action));
        button.textContent = actionLabel(action);
        button.addEventListener("click", function () { submitRawAction(action); });
        list.appendChild(button);
      });
      group.appendChild(list);
      elements["action-menu"].appendChild(group);
    });
  }

  function actionLabel(action) {
    if (!data.isObject(action)) {
      return locale.tr("unknownAction");
    }
    if (action.type === "MULLIGAN") {
      var ids = data.asArray(action.mulligan_entity_ids);
      return ids.length ? locale.tr("replace") + " " + ids.map(labelForEntity).join(locale.locale === "enUS" ? ", " : "、") : locale.tr("keepAll");
    }
    if (action.type === "CHOOSE") {
      return locale.tr("choose") + " " + labelForEntity(action.choice_entity_id);
    }
    if (action.type === "PLAY_CARD") {
      return locale.tr("play") + " " + labelForEntity(action.source_entity_id) + actionSuffix(action);
    }
    if (action.type === "ATTACK") {
      return locale.tr("attackWith") + " " + labelForEntity(action.source_entity_id) + " " + locale.tr("attackTarget") + " " + labelForEntity(action.target_entity_id);
    }
    if (action.type === "USE_HERO_POWER") {
      return locale.tr("usePower") + " " + labelForEntity(action.source_entity_id) + actionSuffix(action);
    }
    if (action.type === "END_TURN") {
      return locale.tr("endTurn");
    }
    return data.labelForType(action.type);
  }

  function actionSuffix(action) {
    var suffix = [];
    if (action.choose_option_entity_id !== undefined) {
      suffix.push(" · " + labelForEntity(action.choose_option_entity_id));
    }
    if (action.target_entity_id !== undefined) {
      suffix.push(" → " + labelForEntity(action.target_entity_id));
    }
    if (action.position !== undefined) {
      suffix.push(" · " + positionLabel(action.position));
    }
    return suffix.join("");
  }

  function renderLog(events) {
    var latestEventSeq = state.current.latestEventSeq;
    dom.clear(elements["event-log"]);
    var list = data.asArray(events).slice().reverse();
    if (!list.length) {
      var empty = document.createElement("li");
      empty.className = "empty-log";
      empty.textContent = locale.tr("publicEvent");
      elements["event-log"].appendChild(empty);
      return;
    }
    list.forEach(function (event) {
      var item = document.createElement("li");
      item.className = "event-item" + (data.safeNumber(event.seq, -1) === latestEventSeq ? " latest" : "");
      var actor = document.createElement("span");
      actor.className = "event-actor " + (event.actor === "opponent" ? "opponent" : "self");
      actor.textContent = event.actor === "opponent" ? locale.tr("eventOpponent") : locale.tr("eventSelf");
      item.appendChild(actor);
      var message = document.createElement("span");
      message.textContent = eventText(event);
      item.appendChild(message);
      if (event.turn !== undefined && event.turn !== null) {
        var turn = document.createElement("span");
        turn.className = "event-turn";
        turn.textContent = locale.tr("eventTurn", { value: event.turn });
        item.appendChild(turn);
      }
      elements["event-log"].appendChild(item);
    });
  }

  function eventText(event) {
    if (!data.isObject(event)) {
      return locale.tr("publicEvent");
    }
    var type = data.labelForType(event.type);
    function visibleName(id, fallback) {
      var card = findVisibleEntity(id);
      return card ? data.cardName(card) : data.safeText(fallback, locale.tr("target"));
    }
    if (event.type === "PLAY_CARD") {
      return locale.tr("play") + " " + visibleName(event.source_entity_id, event.source_name || locale.tr("unknownCard")) + (event.position !== undefined ? locale.tr("playedAt", { value: event.position }) : "");
    }
    if (event.type === "ATTACK") {
      return visibleName(event.source_entity_id, event.source_name || locale.tr("minions", { value: 1 })) + " " + locale.tr("attackTarget") + " " + visibleName(event.target_entity_id, event.target_name || locale.tr("target"));
    }
    if (event.type === "USE_HERO_POWER") {
      return locale.tr("eventHeroPower") + (event.target_name ? locale.tr("arrow") + visibleName(event.target_entity_id, event.target_name) : "");
    }
    if (event.type === "MULLIGAN") {
      return locale.tr("eventMulligan");
    }
    if (event.type === "CHOOSE") {
      return locale.tr("eventChoice") + (event.source_name ? (locale.locale === "enUS" ? ": " : "：") + String(event.source_name) : "");
    }
    return type;
  }

  function sourceTypesFor(sourceId) {
    if (sourceId === null) return [];
    const actionIndex = state.current.actionIndex;
    return ["PLAY_CARD", "ATTACK", "USE_HERO_POWER"].filter((type) =>
      model.sourceActions(actionIndex, type, sourceId).length > 0);
  }

  function targetIds() {
    const selection = state.current.selection;
    const ids = new Set();
    if (selection.sourceId === null) return ids;
    selectedActions().forEach((action) => {
      const id = data.entityId(action.target_entity_id);
      if (id !== null) ids.add(id);
    });
    return ids;
  }

  function labelForEntity(entityIdValue) {
    const id = data.entityId(entityIdValue);
    if (id === null) return locale.tr("target");
    const card = findVisibleEntity(id);
    return card ? data.cardName(card) : locale.tr("entity", { value: id });
  }

  return {
    actionLabel, actionRequiresSelection, cancelSelection, chooseBranch,
    choosePosition, chooseSource, chooseTarget, eventText, findVisibleEntity,
    labelForEntity, maybeSubmitSingle, optionCard, positionLabel,
    renderActions, renderChoiceOptions, renderDecision, renderLog,
    renderPendingChoice, renderQuickActions, renderSourceOptions,
    selectedActions, selectedSummary, submitEndTurn, submitRawAction,
    submitSelected, targetIds, sourceTypesFor, toggleMulligan,
  };
}
