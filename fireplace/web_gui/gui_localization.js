const FALLBACK_COPY = {
  "phase.MULLIGAN": "换牌",
  "phase.CHOICE": "选择",
  "phase.MAIN": "主阶段",
  "phase.GAME_OVER": "对局结束",
  unknownCard: "未知卡牌",
  unknownAction: "未知动作",
  target: "目标",
};

/** Owns browser locale and storage access for the UI. */
export function createLocalization({ storageSource = globalThis, i18n = globalThis.FireplaceI18n } = {}) {
  let currentLocale = "zhCN";

  function normalizeLocale(locale) {
    if (i18n && typeof i18n.normalizeLocale === "function") {
      return i18n.normalizeLocale(locale);
    }
    return locale === "enUS" ? "enUS" : "zhCN";
  }

  function setLocale(locale) {
    currentLocale = normalizeLocale(locale);
    return currentLocale;
  }

  function tr(key, variables) {
    if (i18n && typeof i18n.t === "function") {
      return i18n.t(key, variables, currentLocale);
    }
    const value = FALLBACK_COPY[key] || key;
    return String(value).replace(/\{([a-zA-Z0-9_]+)\}/g, (_, name) => (
      variables && variables[name] !== undefined ? String(variables[name]) : `{${name}}`
    ));
  }

  function readStored(key, fallback) {
    try {
      const value = storageSource.localStorage.getItem(key);
      return value === null || value === undefined ? fallback : value;
    } catch (_error) {
      return fallback;
    }
  }

  function writeStored(key, value) {
    try {
      storageSource.localStorage.setItem(key, value);
    } catch (_error) {
      // Private browsing or disabled storage should not block a local match.
    }
  }

  return {
    get locale() { return currentLocale; },
    normalizeLocale,
    readStored,
    setLocale,
    tr,
    writeStored,
  };
}
