export function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function safeNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function safeText(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback || "";
  return String(value);
}

export function snapshotFingerprint(value) {
  try {
    return JSON.stringify(value);
  } catch (_error) {
    return String(Date.now());
  }
}

export function createDomUtils({ document, window, translate, elements }) {
  let noticeTimer = null;

  function setText(node, value) {
    if (node) node.textContent = safeText(value, "");
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setHidden(node, hidden) {
    if (node) node.hidden = Boolean(hidden);
  }

  function setConnection(text, isError) {
    setText(elements["connection-value"], text);
    if (elements["connection-value"]) {
      elements["connection-value"].classList.toggle("connection-error", Boolean(isError));
    }
  }

  function showNotice(message, kind, timeout) {
    const notice = elements.notice;
    if (!notice) return;
    window.clearTimeout(noticeTimer);
    notice.className = `notice${kind ? ` ${kind}` : ""}`;
    setText(notice, message);
    setHidden(notice, !message);
    if (timeout) noticeTimer = window.setTimeout(() => setHidden(notice, true), timeout);
  }

  function errorMessage(error) {
    if (error instanceof Error) return error.message;
    if (typeof error === "string") return error;
    if (isObject(error) && typeof error.message === "string") return error.message;
    return translate("unknownError");
  }

  return { clear, errorMessage, setConnection, setHidden, setText, showNotice };
}

export function createDataUtils({ model, translate, getLocale }) {
  function entityId(value) {
    return model.id(value);
  }

  function cardName(card) {
    if (!isObject(card)) return translate("unknownCard");
    return safeText(card.name, safeText(card.card_id, translate("unknownCard")));
  }

  function cardText(card) {
    if (!isObject(card) || card.text === undefined || card.text === null) return "";
    const text = String(card.text);
    if (!text || text === String(card.card_id || "")) return "";
    return text.replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]*>/g, "").replace(/\$([0-9]+)/g, "$1");
  }

  function labelForType(type) {
    const labels = {
      MULLIGAN: "replace",
      CHOOSE: "choose",
      PLAY_CARD: "play",
      ATTACK: "attackTarget",
      USE_HERO_POWER: "usePower",
      END_TURN: "endTurn",
    };
    return labels[type] ? translate(labels[type]) : safeText(type, translate("unknownAction"));
  }

  function handSeparator() {
    return getLocale() === "enUS" ? ", " : "，";
  }

  function errorMessage(error) {
    if (error instanceof Error) return error.message;
    if (typeof error === "string") return error;
    if (isObject(error) && typeof error.message === "string") return error.message;
    return translate("unknownError");
  }

  return {
    asArray,
    cardName,
    cardText,
    entityId,
    errorMessage,
    handSeparator,
    isObject,
    labelForType,
    safeNumber,
    safeText,
  };
}
