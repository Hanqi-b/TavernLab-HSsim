export function createBoard(deps) {
  "use strict";
  const {
    document, elements, state, model, data, dom, locale, cards, statusView,
    onChoosePosition, onChooseSource, onChooseTarget, onToggleMulligan,
    onOpenCard, targetIds, sourceTypesFor, selectedActions, positionLabel,
    renderDecision, renderActions, renderLog, renderOutcome, updateAttackLine,
  } = deps;

  function renderSnapshot() {
    var snapshot = state.current.snapshot;
    var actionIndex = state.current.actionIndex;
    var observation = data.isObject(snapshot.observation) ? snapshot.observation : {};
    var self = data.isObject(observation.self) ? observation.self : {};
    var opponent = data.isObject(observation.opponent) ? observation.opponent : {};
    var phase = data.safeText(observation.phase, "UNKNOWN").toUpperCase();

    dom.setText(elements["phase-value"], phaseLabel(phase));
    dom.setText(elements["turn-value"], observation.turn === null || observation.turn === undefined ? locale.tr("status.turn", { value: "—" }) : locale.tr("status.turn", { value: observation.turn }));
    var activeLabel = observation.active_seat === null || observation.active_seat === undefined
      ? "—"
      : String(observation.active_seat) + (observation.active_seat === 0 ? locale.tr("status.youSuffix") : locale.tr("status.opponentSuffix"));
    dom.setText(elements["active-seat-value"], locale.tr("status.active", { value: activeLabel }));
    dom.setText(elements["revision-value"], locale.tr("status.revision", { value: snapshot.revision }));
    dom.setText(elements["mana-value"], manaText(self));
    dom.setText(elements["opponent-mana-value"], manaText(opponent));
    dom.setText(elements["opponent-hand-count"], locale.tr("cardsInHand", { value: data.safeNumber(opponent.hand_count, 0) }));
    renderDeckCount(elements["deck-count"], self.deck_count, "yourDeckCount");
    renderDeckCount(elements["opponent-deck-count"], opponent.deck_count, "opponentDeckCount");
    dom.setText(elements["self-board-count"], boardCountText(self.board));
    dom.setText(elements["opponent-board-count"], boardCountText(opponent.board));
    dom.setText(elements["action-count"], locale.tr("actions", { value: actionIndex.actions.length }));
    dom.setText(elements["fallback-count"], "(" + String(actionIndex.actions.length) + ")");

    renderHiddenHand(opponent.hand_count);
    renderHero(elements["opponent-hero-row"], opponent.hero, false, opponent.hero_power);
    renderHero(elements["self-hero-row"], self.hero, true, self.hero_power);
    renderHeroStatuses(elements["opponent-hero-status"], opponent, false);
    renderHeroStatuses(elements["self-hero-status"], self, true);
    renderExtras(elements["opponent-extras"], opponent, false);
    renderExtras(elements["self-extras"], self, true);
    renderBoard(elements["opponent-board"], opponent.board, false);
    renderBoard(elements["self-board"], self.board, true);
    renderHeroPower(self.hero_power);
    renderHand(self.hand, phase);
    renderDecision();
    renderActions();
    renderLog(snapshot.events);
    renderOutcome(snapshot.outcome, phase);
    updateAttackLine();
  }

  function phaseLabel(phase) {
    return locale.tr("phase." + phase, {}) || phase;
  }

  function manaText(player) {
    var mana = player && player.mana !== undefined ? player.mana : "—";
    var maxMana = player && player.max_mana !== undefined ? player.max_mana : "—";
    return String(mana) + " / " + String(maxMana) + " " + locale.tr("mana");
  }

  function boardCountText(board) {
    var count = data.asArray(board).length;
    return locale.tr("minions", { value: count });
  }

  function renderDeckCount(element, value, labelKey) {
    var count = data.safeNumber(value, 0);
    dom.setText(element, locale.tr("deck", { value: count }));
    element.setAttribute("aria-label", locale.tr(labelKey, { value: count }));
  }

  function renderHiddenHand(count) {
    dom.clear(elements["opponent-hand"]);
    var amount = Math.max(0, data.safeNumber(count, 0));
    for (var index = 0; index < amount; index += 1) {
      var card = document.createElement("span");
      card.className = "hidden-card";
      card.setAttribute("aria-label", locale.tr("opponentHiddenCard", { value: index + 1 }));
      card.setAttribute("data-testid", "hidden-opponent-card");
      elements["opponent-hand"].appendChild(card);
    }
  }

  function entityLabels() {
    var labels = new Map();
    var snapshot = state.current.snapshot;
    if (!snapshot || !data.isObject(snapshot.observation)) {
      return labels;
    }
    var observation = snapshot.observation;
    var self = data.isObject(observation.self) ? observation.self : {};
    var opponent = data.isObject(observation.opponent) ? observation.opponent : {};
    addEntityLabel(labels, self.hero, locale.tr("yourHero") + ": " + data.cardName(self.hero));
    addEntityLabel(labels, self.hero_power, locale.tr("skill") + ": " + data.cardName(self.hero_power));
    addEntityLabel(labels, opponent.hero, locale.tr("opponentHero") + ": " + data.cardName(opponent.hero));
    addEntityLabel(labels, opponent.hero_power, locale.tr("skill") + ": " + data.cardName(opponent.hero_power));
    data.asArray(self.hand).forEach(function (card) { addEntityLabel(labels, card, data.cardName(card)); });
    data.asArray(self.board).forEach(function (card) { addEntityLabel(labels, card, data.cardName(card)); });
    data.asArray(opponent.board).forEach(function (card) { addEntityLabel(labels, card, locale.tr("opponent") + ": " + data.cardName(card)); });
    var pending = data.isObject(observation.pending_choice) ? observation.pending_choice : {};
    data.asArray(pending.options).forEach(function (card) { addEntityLabel(labels, card, data.cardName(card)); });
    data.asArray(self.hand).forEach(function (card) {
      data.asArray(card && card.choose_options).forEach(function (option) { addEntityLabel(labels, option, data.cardName(option)); });
    });
    return labels;
  }

  function addEntityLabel(labels, entity, label) {
    if (!data.isObject(entity)) {
      return;
    }
    var id = data.entityId(entity.entity_id);
    if (id !== null) {
      labels.set(id, label || data.cardName(entity));
    }
  }

  function labelForEntity(entityIdValue) {
    var id = data.entityId(entityIdValue);
    if (id === null) {
      return locale.tr("target");
    }
    return entityLabels().get(id) || locale.tr("entity", { value: id });
  }

  function renderHero(container, hero, own, power) {
    dom.clear(container);
    container.classList.remove("promote-interaction");
    if (own) {
      container.closest(".self-panel").classList.remove("promote-interaction");
    }
    if (!data.isObject(hero)) {
      var empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = locale.tr("noHero");
      container.appendChild(empty);
      return;
    }
    var id = data.entityId(hero.entity_id);
    var target = targetIds().has(id);
    var sourceTypes = sourceTypesFor(id);
    container.classList.toggle("promote-interaction", own && (target || sourceTypes.length > 0));
    if (own && (target || sourceTypes.length > 0)) {
      container.closest(".self-panel").classList.add("promote-interaction");
    }
    var wrapper = cards.createEntityCard(hero, "hero-card " + (target ? "targetable " : "") + (sourceTypes.length ? "sourceable" : ""), function () {
      if (target && onChooseTarget(id)) {
        return;
      }
      if (sourceTypes.length) {
        onChooseSource(sourceTypes[0], id);
      }
    });
    wrapper.classList.add(own ? "own-hero" : "enemy-hero");
    var art = cards.createCardArt(hero, "art");
    wrapper.appendChild(art);
    var copy = document.createElement("div");
    copy.className = "hero-copy";
    copy.appendChild(cards.cardTitle(hero));
    var subtitle = document.createElement("p");
    subtitle.className = "card-subtitle";
    subtitle.textContent = own ? locale.tr("yourHero") : locale.tr("opponentHero");
    copy.appendChild(subtitle);
    if (!own && data.isObject(power)) {
      var powerSummary = document.createElement("p");
      powerSummary.className = "card-subtitle public-power";
      powerSummary.textContent = locale.tr("skill") + ": " + data.cardName(power) +
        (power.cost === undefined || power.cost === null ? "" : " · " + locale.tr("cost") + " " + String(power.cost));
      copy.appendChild(powerSummary);
    }
    copy.appendChild(cards.createCharacterStats(hero, data.safeNumber(hero.atk, 0) > 0));
    wrapper.appendChild(copy);
    container.appendChild(wrapper);
  }

  function renderExtras(container, player, own) {
    dom.clear(container);
    var weapon = data.isObject(player.weapon) ? player.weapon : null;
    if (weapon) {
      var weaponButton = document.createElement("button");
      weaponButton.type = "button";
      weaponButton.className = "extra-chip weapon-chip";
      weaponButton.setAttribute("data-testid", own ? "self-weapon" : "opponent-weapon");
      var attack = data.safeNumber(weapon.atk, 0);
      var durability = data.safeNumber(weapon.durability, 0);
      var weaponName = data.cardName(weapon);
      var attackLabel = String(attack) + " " + locale.tr("attack");
      var durabilityLabel = String(durability) + " " + locale.tr("durability");
      weaponButton.setAttribute("aria-label", locale.tr("weapon") + ": " + weaponName + " · " + attackLabel + " / " + durabilityLabel);
      weaponButton.appendChild(cards.createCardArt(weapon, "tile"));
      var weaponCopy = document.createElement("span");
      weaponCopy.className = "weapon-copy";
      var weaponNameNode = document.createElement("span");
      weaponNameNode.className = "weapon-name";
      weaponNameNode.setAttribute("data-testid", "weapon-name");
      weaponNameNode.textContent = locale.tr("weapon") + ": " + weaponName;
      weaponCopy.appendChild(weaponNameNode);
      var weaponStats = document.createElement("span");
      weaponStats.className = "weapon-stats";
      weaponStats.setAttribute("data-testid", "weapon-stats");
      weaponStats.setAttribute("aria-label", attackLabel + " / " + durabilityLabel);
      var attackNode = document.createElement("span");
      attackNode.className = "weapon-stat weapon-attack";
      attackNode.textContent = attackLabel;
      weaponStats.appendChild(attackNode);
      var separator = document.createElement("span");
      separator.className = "weapon-stat-separator";
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "/";
      weaponStats.appendChild(separator);
      var durabilityNode = document.createElement("span");
      durabilityNode.className = "weapon-stat weapon-durability";
      durabilityNode.textContent = durabilityLabel;
      weaponStats.appendChild(durabilityNode);
      weaponCopy.appendChild(weaponStats);
      weaponButton.appendChild(weaponCopy);
      weaponButton.addEventListener("click", function () { onOpenCard(weapon); });
      container.appendChild(weaponButton);
    }
    dom.setHidden(container, !container.childNodes.length);
  }

  function renderHeroStatuses(container, player, own) {
    dom.clear(container);
    if (!data.isObject(player)) {
      dom.setHidden(container, true);
      return;
    }

    var quests = data.asArray(player.quests).filter(data.isObject);
    if (own) {
      var secrets = data.asArray(player.secrets).filter(data.isObject);
      if (secrets.length) {
        appendHeroStatusGroup(container, "secret", locale.tr("secrets"), secrets, true);
      }
    } else {
      var secretCount = Math.max(0, data.safeNumber(player.secrets_count, 0));
      if (secretCount > 0) {
        appendHiddenSecretGroup(container, secretCount, player.secret_classes);
      }
    }
    if (quests.length) {
      appendHeroStatusGroup(container, "quest", locale.tr("quests"), quests, own);
    }
    dom.setHidden(container, !container.childNodes.length);
  }

  function appendHeroStatusGroup(container, kind, label, cards, own) {
    var group = document.createElement("section");
    group.className = "hero-status-group hero-status-group-" + kind;
    group.setAttribute("aria-label", label);
    var heading = document.createElement("h3");
    heading.className = "hero-status-heading";
    heading.textContent = label;
    group.appendChild(heading);
    var list = document.createElement("div");
    list.className = "hero-status-list";
    cards.forEach(function (card) {
      list.appendChild(createHeroStatusCard(card, kind, own));
    });
    group.appendChild(list);
    container.appendChild(group);
  }

  function appendHiddenSecretGroup(container, count, secretClasses) {
    var group = document.createElement("section");
    group.className = "hero-status-group hero-status-group-secret opponent-secret-group";
    group.setAttribute("aria-label", locale.tr("opponentSecrets", { value: count }));
    var heading = document.createElement("h3");
    heading.className = "hero-status-heading";
    heading.textContent = locale.tr("secrets");
    group.appendChild(heading);
    var tokenRack = document.createElement("div");
    tokenRack.className = "hero-status-list secret-token-list";
    tokenRack.setAttribute("aria-label", locale.tr("opponentSecrets", { value: count }));
    var classGroups = normalizeSecretClasses(secretClasses);
    for (var index = 0; index < count; index += 1) {
      var token = document.createElement("span");
      token.className = "secret-back-token";
      var labels = (classGroups[index] || []).map(secretClassLabel);
      var classText = labels.join(locale.tr("secretClassSeparator"));
      var tokenLabel = locale.tr("opponentSecret", {
        value: index + 1,
        classes: classText || locale.tr("secretClassUnknown"),
      });
      token.setAttribute("aria-label", tokenLabel);
      token.setAttribute("role", "img");
      token.title = tokenLabel;
      token.setAttribute("data-testid", "opponent-secret");
      token.style.setProperty("--secret-index", String(index));
      var art = document.createElement("span");
      art.className = "secret-back-art";
      art.setAttribute("aria-hidden", "true");
      token.appendChild(art);
      if (classText) {
        var classLabel = document.createElement("span");
        classLabel.className = "secret-class-label";
        classLabel.textContent = classText;
        classLabel.setAttribute("aria-hidden", "true");
        token.appendChild(classLabel);
      }
      tokenRack.appendChild(token);
    }
    var statusLine = document.createElement("div");
    statusLine.className = "secret-status-line";
    statusLine.appendChild(tokenRack);
    var countLabel = document.createElement("span");
    countLabel.className = "secret-count-label";
    countLabel.setAttribute("data-testid", "opponent-secret-count");
    countLabel.setAttribute("aria-label", locale.tr("opponentSecrets", { value: count }));
    countLabel.textContent = "×" + String(count);
    statusLine.appendChild(countLabel);
    group.appendChild(statusLine);
    container.appendChild(group);
  }

  function normalizeSecretClasses(value) {
    var groups = data.asArray(value);
    return groups.map(function (group) {
      return data.asArray(group).map(function (code) {
        return data.safeText(code, "").trim().toUpperCase();
      }).filter(Boolean);
    });
  }

  function secretClassLabel(code) {
    var key = "class." + code;
    var translated = locale.tr(key);
    return translated === key ? code : translated;
  }

  function createHeroStatusCard(card, kind, own) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "hero-status-card " + kind + "-status-card";
    button.setAttribute("data-testid", kind === "quest"
      ? (own ? "self-quest" : "opponent-quest")
      : "self-secret");
    var progress = cards.optionalNumber(card.progress);
    var total = cards.optionalNumber(card.progress_total);
    var progressText = "";
    if (kind === "quest" && progress !== null) {
      progressText = total === null
        ? locale.tr("questProgressValue", { value: progress })
        : locale.tr("questProgress", { value: progress, total: total });
    }
    var label = data.cardName(card) + (progressText ? " · " + progressText : "");
    button.setAttribute("aria-label", label);
    button.title = label;
    button.appendChild(cards.createCardArt(card, "tile"));
    var copy = document.createElement("span");
    copy.className = "hero-status-copy";
    var name = document.createElement("span");
    name.className = "hero-status-name";
    name.textContent = data.cardName(card);
    copy.appendChild(name);
    if (progressText) {
      var progressNode = document.createElement("span");
      progressNode.className = "quest-progress";
      progressNode.textContent = progressText;
      copy.appendChild(progressNode);
    }
    button.appendChild(copy);
    button.addEventListener("click", function () { onOpenCard(card); });
    return button;
  }

  function renderBoard(container, board, own) {
    statusView.hideTooltip();
    dom.clear(container);
    var boardCards = data.asArray(board);
    var selection = state.current.selection;
    var positions = own && selection.sourceId !== null && selection.type === "PLAY_CARD"
      ? model.uniqueValues(selectedActions(), "position").slice().sort(function (left, right) { return left - right; })
      : [];
    boardCards.forEach(function (card, index) {
      if (positions.indexOf(index) >= 0) {
        container.appendChild(createPositionSlot(index));
      }
      var id = data.entityId(card && card.entity_id);
      var target = targetIds().has(id);
      var sourceTypes = own ? sourceTypesFor(id) : [];
      var wrapper = cards.createEntityCard(card, "card board-card " + (target ? "targetable " : "") + (sourceTypes.length ? "sourceable" : ""), function () {
        if (target && onChooseTarget(id)) {
          return;
        }
        if (sourceTypes.length) {
          onChooseSource(sourceTypes[0], id);
        }
      });
      wrapper.setAttribute("data-entity-id", String(id === null ? "" : id));
      wrapper.appendChild(cards.createCardArt(card, "art"));
      statusView.decorateBoardCard(wrapper, card, locale.tr);
      var content = document.createElement("div");
      content.className = "card-content";
      content.appendChild(cards.cardTitle(card));
      content.appendChild(cards.createCharacterStats(card, true, true));
      cards.appendCardText(content, card);
      wrapper.appendChild(content);
      container.appendChild(wrapper);
    });
    if (positions.indexOf(boardCards.length) >= 0) {
      container.appendChild(createPositionSlot(boardCards.length));
    }
  }

  function createPositionSlot(position) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "board-slot";
    button.setAttribute("data-position", String(position));
    button.setAttribute("aria-label", locale.tr("positionNumber", { value: positionLabel(position) }));
    button.textContent = "+";
    button.addEventListener("click", function () { onChoosePosition(position); });
    return button;
  }

  function renderHeroPower(power) {
    dom.clear(elements["hero-power-row"]);
    if (!data.isObject(power)) {
      return;
    }
    var id = data.entityId(power.entity_id);
    var sourceTypes = sourceTypesFor(id);
    var wrapper = cards.createEntityCard(power, "power-card " + (sourceTypes.length ? "sourceable" : ""), function () {
      if (sourceTypes.length) {
        onChooseSource(sourceTypes[0], id);
      }
    });
    wrapper.appendChild(cards.createCardArt(power, "art"));
    var copy = document.createElement("div");
    copy.className = "power-copy";
    copy.appendChild(cards.cardTitle(power, locale.tr("skill") + ": "));
    var details = document.createElement("p");
    details.className = "card-subtitle";
    details.textContent = (power.cost === undefined || power.cost === null ? "" : locale.tr("cost") + " " + String(power.cost) + " · ") +
      (power.is_usable ? locale.tr("canUse") : (power.exhausted ? locale.tr("usedThisTurn") : locale.tr("notAvailable")));
    copy.appendChild(details);
    cards.appendCardText(copy, power);
    wrapper.appendChild(copy);
    elements["hero-power-row"].appendChild(wrapper);
  }

  function renderHand(hand, phase) {
    dom.clear(elements["hand"]);
    var selection = state.current.selection;
    data.asArray(hand).forEach(function (card) {
      var id = data.entityId(card && card.entity_id);
      var sourceTypes = phase === "MAIN" ? sourceTypesFor(id) : [];
      var playActions = phase === "MAIN"
        ? model.sourceActions(state.current.actionIndex, "PLAY_CARD", id)
        : [];
      var canPlay = playActions.length > 0;
      var poweredUp = canPlay && Boolean(card && card.powered_up);
      var mulliganSelected = selection.mulliganIds.some(function (value) { return value === id; });
      var wrapper = cards.createEntityCard(card, "card hand-card " + (canPlay ? "sourceable playable" : "") +
        (poweredUp ? " powered-up" : "") + (mulliganSelected ? " mulligan-selected" : ""), function () {
        if (phase === "MULLIGAN") {
          onToggleMulligan(id);
        } else if (sourceTypes.length) {
          onChooseSource(sourceTypes[0], id);
        }
      });
      wrapper.setAttribute("data-entity-id", String(id === null ? "" : id));
      wrapper.setAttribute("data-testid", "hand-card");
      wrapper.setAttribute("data-playable", canPlay ? "true" : "false");
      wrapper.setAttribute("data-powered-up", poweredUp ? "true" : "false");
      wrapper.setAttribute("aria-label", cards.handCardLabel(card, canPlay, poweredUp));
      wrapper.appendChild(cards.createCardArt(card, "render", { liveStats: true }));
      var content = document.createElement("div");
      content.className = "card-content";
      content.appendChild(cards.cardTitle(card));
      if (data.asArray(card && card.choose_options).length) {
        content.appendChild(cards.createBadge(locale.tr("selectOne"), "branch-badge"));
      }
      cards.appendCardText(content, card);
      wrapper.appendChild(content);
      elements["hand"].appendChild(wrapper);
    });
  }

  return {
    boardCountText, entityLabels, labelForEntity, manaText, phaseLabel,
    renderBoard, renderExtras, renderHand, renderHero, renderHeroPower,
    renderHeroStatuses, renderHiddenHand, renderSnapshot,
  };
}
