export function createCards(deps) {
  "use strict";
  const {
    document, window, translate: tr, locale,
    isObject, safeText, cardName, cardText, entityId, onOpenCard,
  } = deps;
  const assetRequests = new Map();

  function optionalNumber(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    var number = typeof value === "number" ? value : Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function cardHealthValue(card) {
    if (!isObject(card)) {
      return null;
    }
    var health = optionalNumber(card.health);
    return health === null ? optionalNumber(card.max_health) : health;
  }

  function cardStatValues(card) {
    if (!isObject(card)) {
      return [];
    }
    var values = [];
    function add(name, label, current, printed, changeType) {
      var live = optionalNumber(current);
      if (live === null) {
        return;
      }
      values.push({
        name: name,
        label: label,
        current: live,
        printed: optionalNumber(printed),
        changeType: changeType,
      });
    }
    add("cost", tr("cost"), card.cost, card.printed_cost, "cost");
    add("attack", tr("attack"), card.atk, card.printed_atk, "stat");
    var durability = optionalNumber(card.durability);
    if (durability !== null) {
      add("durability", tr("durability"), durability, card.printed_durability, "stat");
    } else {
      add("health", tr("health"), cardHealthValue(card), card.printed_health, "stat");
    }
    return values;
  }

  function statChangeClass(value) {
    if (value.printed === null || value.current === value.printed) {
      return "unchanged";
    }
    if (value.changeType === "cost") {
      return value.current < value.printed ? "cost-lower" : "cost-higher";
    }
    return value.current > value.printed ? "stat-higher" : "stat-lower";
  }

  function handCardLabel(card, canPlay, poweredUp) {
    var parts = [cardName(card)];
    cardStatValues(card).forEach(function (value) {
      var detail = tr("handStatCurrent", { name: value.label, value: value.current });
      if (value.printed !== null && value.current !== value.printed) {
        detail += " " + tr("handStatPrinted", { name: value.label, value: value.printed });
        detail += " " + tr(value.current > value.printed ? "handStatIncreased" : "handStatDecreased");
      }
      parts.push(detail);
    });
    if (canPlay) {
      parts.push(tr("play"));
    }
    if (poweredUp) {
      parts.push(tr("handConditionMet"));
    }
    return parts.join(locale.locale === "enUS" ? ", " : "，");
  }

  function createLiveStatsOverlay(card) {
    var values = cardStatValues(card);
    if (!values.length) {
      return null;
    }
    var overlay = document.createElement("div");
    overlay.className = "card-live-stats";
    overlay.setAttribute("aria-hidden", "true");
    values.forEach(function (value) {
      var node = document.createElement("span");
      node.className = "card-live-stat card-live-stat-" + value.name + " " + statChangeClass(value);
      node.textContent = String(value.current);
      node.title = value.label + " " + String(value.current);
      overlay.appendChild(node);
    });
    return overlay;
  }

  function resetLiveStatsOverlay(overlay) {
    if (!overlay) {
      return;
    }
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
  }

  function syncLiveStatsOverlay(art, image, overlay) {
    if (!art || !image || !overlay) {
      return;
    }
    var artWidth = art.clientWidth;
    var artHeight = art.clientHeight;
    var imageWidth = image.naturalWidth;
    var imageHeight = image.naturalHeight;
    if (!artWidth || !artHeight || image.hidden || !imageWidth || !imageHeight) {
      resetLiveStatsOverlay(overlay);
      return;
    }
    var scale = Math.min(artWidth / imageWidth, artHeight / imageHeight);
    var renderedWidth = imageWidth * scale;
    var renderedHeight = imageHeight * scale;
    overlay.style.top = ((artHeight - renderedHeight) / 2) + "px";
    overlay.style.left = ((artWidth - renderedWidth) / 2) + "px";
    overlay.style.width = renderedWidth + "px";
    overlay.style.height = renderedHeight + "px";
  }

  function refreshLiveStatsOverlays() {
    document.querySelectorAll(".card-live-stats").forEach(function (overlay) {
      var art = overlay.parentElement;
      var image = art && art.querySelector("img");
      syncLiveStatsOverlay(art, image, overlay);
    });
  }

  function createEntityCard(card, className, onSelect) {
    var wrapper = document.createElement("article");
    wrapper.className = className + " card-zoomable";
    wrapper.setAttribute("aria-label", cardName(card));
    wrapper.title = tr("viewCard", { value: cardName(card) });
    var visibleId = entityId(card && card.entity_id);
    if (visibleId !== null) {
      wrapper.setAttribute("data-entity-id", String(visibleId));
    }
    if (typeof onSelect === "function") {
      wrapper.setAttribute("role", "button");
      wrapper.tabIndex = 0;
      wrapper.addEventListener("click", function () {
        onSelect();
      });
      wrapper.addEventListener("keydown", function (event) {
        if (event.target === wrapper && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onSelect();
        }
      });
    }
    var inspect = document.createElement("button");
    inspect.type = "button";
    inspect.className = "card-inspect";
    inspect.textContent = "⌕";
    inspect.setAttribute("aria-label", tr("viewCard", { value: cardName(card) }));
    inspect.setAttribute("data-testid", "card-inspect");
    inspect.addEventListener("click", function (event) {
      event.stopPropagation();
      onOpenCard(card);
    });
    wrapper.appendChild(inspect);
    return wrapper;
  }

  function createCardArt(card, kind, options) {
    var art = document.createElement("div");
    art.className = "card-art asset-placeholder";
    var liveStats = options && options.liveStats ? createLiveStatsOverlay(card) : null;
    var cardId = isObject(card) ? card.card_id : null;
    if (cardId) {
      var image = document.createElement("img");
      image.alt = cardName(card) + " " + tr("cardArt");
      image.loading = "lazy";
      image.hidden = true;
      var preferredKind = kind || "render";
      var imageRank = -1;
      image.addEventListener("load", function () {
        art.classList.remove("asset-placeholder");
        syncLiveStatsOverlay(art, image, liveStats);
      });
      image.addEventListener("error", function () {
        image.hidden = true;
        art.classList.add("asset-placeholder");
        resetLiveStatsOverlay(liveStats);
      });
      art.appendChild(image);
      function offerAsset(assetKind, result) {
        if (!result || !result.url || !image.isConnected) {
          return;
        }
        var rank = assetKind === preferredKind ? 2 : 1;
        if (rank > imageRank) {
          imageRank = rank;
          art.classList.remove("asset-kind-render", "asset-kind-art", "asset-kind-tile");
          art.classList.add("asset-kind-" + assetKind);
          image.src = result.url;
          image.hidden = false;
        }
      }
      function loadKind(assetKind, remainingRetries) {
        requestAsset(assetKind, String(cardId)).then(function (result) {
          if (result && result.url) {
            offerAsset(assetKind, result);
          } else if (remainingRetries > 0 && art.isConnected) {
            // A transient 404 or offline placeholder should not make this
            // visible card permanently blank for the rest of the match.
            window.setTimeout(function () {
              if (art.isConnected) {
                loadKind(assetKind, remainingRetries - 1);
              }
            }, 16000);
          }
        });
      }
      if (preferredKind !== "render") {
        // A cached full render gives an immediate offline fallback while the
        // cropped illustration is fetched.  Neither URL leaves this server.
        loadKind("render", 2);
      }
      loadKind(preferredKind, 2);
    }
    var mark = document.createElement("span");
    mark.className = "asset-mark";
    mark.textContent = cardId ? "✦" : "?";
    art.appendChild(mark);
    if (liveStats) {
      art.appendChild(liveStats);
      syncLiveStatsOverlay(art, cardId ? art.querySelector("img") : null, liveStats);
    }
    return art;
  }

  function delay(milliseconds) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, milliseconds);
    });
  }

  function requestAsset(kind, cardId) {
    var key = kind + "|" + cardId;
    var existing = assetRequests.get(key);
    if (existing && (!existing.expiresAt || Date.now() < existing.expiresAt)) {
      return existing.promise;
    }
    assetRequests.delete(key);
    var entry = { objectUrl: null, promise: null, cancelled: false, expiresAt: 0 };
    function retryLater() {
      entry.expiresAt = Date.now() + 15000;
      return null;
    }
    var assetUrl = "/assets/" + encodeURIComponent(kind) + "/" + encodeURIComponent(cardId);
    entry.promise = (async function () {
      var networkErrors = 0;
      for (;;) {
        if (entry.cancelled) {
          return null;
        }
        try {
          var response = await window.fetch(assetUrl, { cache: "no-store" });
          if (entry.cancelled) {
            return null;
          }
          if (response.status === 202) {
            // The local resolver is still downloading.  One shared poll per
            // card survives DOM redraws and does not occupy a connection.
            await delay(1300);
            continue;
          }
          if (!response.ok) {
            return retryLater();
          }
          if (response.headers.get("X-Asset-Placeholder") === "1") {
            return retryLater();
          }
          var blob = await response.blob();
          if (entry.cancelled) {
            return null;
          }
          if (!blob.size || !blob.type.startsWith("image/")) {
            return retryLater();
          }
          entry.objectUrl = window.URL.createObjectURL(blob);
          return { url: entry.objectUrl };
        } catch (error) {
          networkErrors += 1;
          if (networkErrors >= 10) {
            return retryLater();
          }
          await delay(2000);
        }
      }
    }());
    assetRequests.set(key, entry);
    return entry.promise;
  }

  function cardTitle(card, prefix) {
    var title = document.createElement("p");
    title.className = "card-name";
    title.textContent = safeText(prefix, "") + cardName(card);
    return title;
  }

  function appendCardText(container, card) {
    var text = cardText(card);
    if (!text) {
      return;
    }
    var node = document.createElement("p");
    node.className = "card-text";
    node.textContent = text;
    container.appendChild(node);
  }

  function createCharacterStats(character, includeAttack, compactHealth) {
    var stats = document.createElement("div");
    stats.className = "stats";
    if (includeAttack && character.atk !== undefined) {
      stats.appendChild(createStat("attack", tr("attack"), character.atk));
    }
    if (character.health !== undefined) {
      var health = !compactHealth && character.max_health !== undefined && character.max_health !== null
        ? String(character.health) + " / " + String(character.max_health)
        : character.health;
      var healthStat = createStat("health", tr("health"), health);
      if (compactHealth && character.max_health !== undefined && character.max_health !== null) {
        healthStat.setAttribute("aria-label", tr("health") + " " + String(character.health) + " / " + String(character.max_health));
        healthStat.title = tr("health") + " " + String(character.health) + " / " + String(character.max_health);
      }
      stats.appendChild(healthStat);
    }
    if (character.armor !== undefined && character.armor) {
      stats.appendChild(createStat("armor", tr("armor"), character.armor));
    }
    return stats;
  }

  function createStat(kind, label, value) {
    var stat = document.createElement("span");
    stat.className = "stat " + kind;
    var strong = document.createElement("strong");
    strong.textContent = safeText(value, "—");
    stat.appendChild(strong);
    var suffix = document.createElement("span");
    suffix.textContent = label;
    stat.appendChild(suffix);
    return stat;
  }

  function createBadge(text, extraClass) {
    var badge = document.createElement("span");
    badge.className = "badge" + (extraClass ? " " + extraClass : "");
    badge.textContent = safeText(text, "");
    return badge;
  }

  function resetAssets() {
    assetRequests.forEach(function (entry) {
      entry.cancelled = true;
      if (entry.objectUrl) window.URL.revokeObjectURL(entry.objectUrl);
    });
    assetRequests.clear();
  }

  return {
    appendCardText,
    cardStatValues,
    cardTitle,
    createBadge,
    createCardArt,
    createCharacterStats,
    createEntityCard,
    createLiveStatsOverlay,
    createStat,
    handCardLabel,
    optionalNumber,
    refreshLiveStatsOverlays,
    resetAssets,
    resetLiveStatsOverlay,
    syncLiveStatsOverlay,
  };
}
