/*
 * Static printed card faces for the catalog and collection pages.
 *
 * This module intentionally knows nothing about match entities or live stats.
 * It owns only the portrait render asset, its loading lifecycle, and the
 * metadata fallback shown while a render is pending or unavailable.
 */

const RETRY_DELAYS = [250, 750, 1500, 3000, 5000];
const MAX_ATTEMPTS = RETRY_DELAYS.length + 1;
const RETRY_CYCLE_DELAY = RETRY_DELAYS[RETRY_DELAYS.length - 1];
let descriptionSequence = 0;

function safeText(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function numberValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? Math.trunc(number) : null;
}

function firstNumber(card, ...keys) {
  for (const key of keys) {
    const value = numberValue(card?.[key]);
    if (value !== null) return value;
  }
  return null;
}

function cardId(card) {
  return safeText(card?.id, safeText(card?.card_id, ""));
}

function cardName(card, copy) {
  return safeText(card?.name) || cardId(card) || copy.unknownCard || "Unknown card";
}

function cardRules(card, copy) {
  return safeText(card?.text) || safeText(card?.rulesText) || copy.noRules || "No card text available.";
}

function faceCopy(value = {}) {
  return {
    cost: safeText(value.cost, "Cost"),
    attack: safeText(value.attack, "Attack"),
    health: safeText(value.health, "Health"),
    durability: safeText(value.durability, "Durability"),
    rules: safeText(value.rules, "Card text"),
    noRules: safeText(value.noRules, "No card text available."),
    loading: safeText(value.loading, "Loading card render…"),
    pending: safeText(value.pending, "Card render is still preparing."),
    unavailable: safeText(value.unavailable, "Card render unavailable."),
    cardImage: safeText(value.cardImage, "card image"),
    unknownCard: safeText(value.unknownCard, "Unknown card"),
  };
}

function setState(record, state, message) {
  const { face, image, fallback, status } = record;
  if (!face || !image || !fallback) return;
  face.dataset.imageState = state;
  image.dataset.imageState = state;
  image.hidden = state !== "loaded";
  fallback.hidden = state === "loaded";
  if (state === "loaded") {
    fallback.setAttribute("aria-hidden", "true");
  } else {
    fallback.removeAttribute("aria-hidden");
  }
  if (status) status.textContent = message || "";
}

function renderAssetUrl(cardIdValue, locale) {
  return `/catalog/assets/render/${encodeURIComponent(cardIdValue)}?locale=${encodeURIComponent(locale)}`;
}

function imageHasDimensions(image) {
  return image.naturalWidth > 0 && image.naturalHeight > 0;
}

function faceStats(card, copy) {
  const type = safeText(card?.type).toUpperCase();
  if (type === "WEAPON") {
    return [
      { name: "attack", label: copy.attack, value: firstNumber(card, "attack", "atk", "printed_atk") },
      { name: "durability", label: copy.durability, value: firstNumber(card, "durability", "max_durability", "printed_durability") },
    ];
  }
  if (type !== "MINION" && type !== "HERO") return [];
  return [
    { name: "attack", label: copy.attack, value: firstNumber(card, "attack", "atk", "printed_atk") },
    { name: "health", label: copy.health, value: firstNumber(card, "health", "max_health", "printed_health") },
  ];
}

function faceDescription(card, copy) {
  const name = cardName(card, copy);
  const rules = cardRules(card, copy);
  const cost = firstNumber(card, "cost", "printed_cost");
  const value = (number) => number === null ? "—" : String(number);
  const stats = faceStats(card, copy).map((stat) => `${stat.label}: ${value(stat.value)}`);
  return [`${name}.`, `${copy.rules}: ${rules}.`, `${copy.cost}: ${value(cost)}.`, ...stats.map((stat) => `${stat}.`)].join(" ");
}

function waitForImage(window, image) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timeout = null;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      if (timeout !== null) window.clearTimeout(timeout);
      image.removeEventListener("load", onLoad);
      image.removeEventListener("error", onError);
      callback(value);
    };
    const onLoad = () => finish(resolve);
    const onError = () => finish(reject, new Error("image load failed"));
    timeout = window.setTimeout(() => {
      // Some Chromium builds do not expose a load event for an SVG object URL
      // that starts hidden. Once it is complete, the blob has still been
      // validated by the browser and is safe to display.
      if (image.complete && imageHasDimensions(image)) finish(resolve);
      else finish(reject, new Error("image load timed out"));
    }, 1500);
    image.addEventListener("load", onLoad, { once: true });
    image.addEventListener("error", onError, { once: true });
    if (image.complete && imageHasDimensions(image)) {
      window.queueMicrotask?.(() => {
        if (image.complete && imageHasDimensions(image)) finish(resolve);
      });
    }
  });
}

function makeStat(document, name, label, value) {
  const node = document.createElement("span");
  node.className = `static-card-face-stat static-card-face-stat-${name}`;
  node.dataset.stat = name;
  const number = document.createElement("strong");
  number.textContent = value === null ? "—" : String(value);
  node.append(number);
  const text = document.createElement("small");
  text.textContent = label;
  node.append(text);
  return node;
}

export function createStaticCardFace(card, options = {}) {
  const document = options.document || globalThis.document;
  const locale = options.locale || "zhCN";
  const copy = faceCopy(options.copy);
  const id = cardId(card);
  const name = cardName(card, copy);
  const rules = cardRules(card, copy);
  const face = document.createElement("div");
  face.className = `static-card-face${options.className ? ` ${options.className}` : ""}`;
  face.dataset.cardFace = "static";
  face.dataset.cardId = id;
  face.dataset.locale = locale;

  const fallback = document.createElement("div");
  fallback.className = "static-card-face-fallback";
  fallback.dataset.fallback = "true";

  const fallbackHeader = document.createElement("div");
  fallbackHeader.className = "static-card-face-fallback-header";
  const fallbackCost = makeStat(document, "cost", copy.cost, firstNumber(card, "cost", "printed_cost"));
  fallbackCost.classList.add("static-card-face-cost");
  fallbackHeader.append(fallbackCost);
  const fallbackType = document.createElement("span");
  fallbackType.className = "static-card-face-type";
  fallbackType.textContent = safeText(card?.type, "");
  fallbackHeader.append(fallbackType);
  fallback.append(fallbackHeader);

  const fallbackName = document.createElement("strong");
  fallbackName.className = "static-card-face-name";
  fallbackName.textContent = name;
  fallback.append(fallbackName);

  const rulesHeading = document.createElement("span");
  rulesHeading.className = "static-card-face-rules-label";
  rulesHeading.textContent = copy.rules;
  fallback.append(rulesHeading);
  const fallbackRules = document.createElement("p");
  fallbackRules.className = "static-card-face-rules";
  fallbackRules.textContent = rules;
  fallback.append(fallbackRules);

  const stats = faceStats(card, copy);
  if (stats.length) {
    const fallbackStats = document.createElement("div");
    fallbackStats.className = "static-card-face-stats";
    stats.forEach((stat) => fallbackStats.append(makeStat(document, stat.name, stat.label, stat.value)));
    fallback.append(fallbackStats);
  }

  const fallbackStatus = document.createElement("span");
  fallbackStatus.className = "static-card-face-status";
  fallbackStatus.setAttribute("role", "status");
  fallbackStatus.textContent = copy.loading;
  fallback.append(fallbackStatus);

  const image = document.createElement("img");
  image.className = "static-card-face-image";
  image.dataset.assetKind = "render";
  image.dataset.imageState = "waiting";
  image.alt = `${name} · ${copy.cardImage}`;
  image.loading = options.eager ? "eager" : "lazy";
  image.decoding = "async";
  image.hidden = true;
  face.append(fallback, image);

  const description = document.createElement("span");
  description.className = "static-card-face-a11y";
  description.id = `static-card-face-description-${++descriptionSequence}`;
  description.textContent = faceDescription(card, copy);
  face.dataset.descriptionId = description.id;
  face.append(description);

  const manager = options.manager;
  if (manager && typeof manager.observe === "function") {
    manager.observe(face, card, { eager: options.eager === true });
  }
  return face;
}

export function createStaticCardFaceManager(options = {}) {
  const window = options.window || globalThis.window;
  const document = options.document || window?.document || globalThis.document;
  const locale = options.locale || "zhCN";
  const copy = faceCopy(options.copy);
  const fetchImpl = options.fetch || window?.fetch?.bind(window) || globalThis.fetch;
  const objectUrls = new Set();
  const records = new Map();
  let generation = 0;
  let sequence = 0;
  let observer = null;

  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function isCurrent(record) {
    return !record.cancelled && record.generation === generation &&
      record.face.isConnected && records.get(record.face) === record;
  }

  function mark(record, state, message) {
    if (!isCurrent(record)) return;
    setState(record, state, message);
  }

  function clearRetryTimer(record) {
    if (record.retryTimer === null) return;
    window.clearTimeout(record.retryTimer);
    record.retryTimer = null;
  }

  function schedulePendingRetry(record) {
    if (!isCurrent(record) || record.retryTimer !== null) return;
    record.retryTimer = window.setTimeout(() => {
      record.retryTimer = null;
      if (!isCurrent(record)) return;
      // The previous promise has completed before this bounded backoff timer
      // can fire, so this starts one new request cycle without overlap.
      record.promise = null;
      void load(record);
    }, RETRY_CYCLE_DELAY);
  }

  async function load(record) {
    if (!isCurrent(record) || record.promise || record.retryTimer !== null) return record.promise;
    record.promise = (async () => {
      const url = renderAssetUrl(record.id, record.locale);
      record.image.dataset.assetUrl = url;
      record.face.dataset.assetUrl = url;
      mark(record, "loading", copy.loading);
      let lastError = null;
      let pendingExhausted = false;
      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
        if (!isCurrent(record)) return;
        try {
          const response = await fetchImpl(url, {
            cache: "no-store",
            signal: record.controller?.signal,
          });
          if (!isCurrent(record)) return;
          if (response.status === 202) {
            mark(record, "pending", copy.pending);
            if (attempt < MAX_ATTEMPTS - 1) {
              await delay(RETRY_DELAYS[attempt]);
              continue;
            }
            pendingExhausted = true;
            break;
          }
          if (!response.ok) {
            const error = new Error(`HTTP ${response.status}`);
            error.retryable = response.status >= 500 || response.status === 408 || response.status === 429;
            throw error;
          }
          if (response.headers?.get?.("X-Asset-Placeholder") === "1") {
            mark(record, "placeholder", copy.unavailable);
            return;
          }
          const blob = await response.blob();
          if (!blob.size || (blob.type && !blob.type.startsWith("image/"))) {
            throw new Error("invalid image response");
          }
          if (!isCurrent(record)) return;
          const createObjectUrl = window?.URL?.createObjectURL;
          const objectUrl = typeof createObjectUrl === "function"
            ? createObjectUrl.call(window.URL, blob)
            : url;
          if (objectUrl !== url) objectUrls.add(objectUrl);
          if (!isCurrent(record)) {
            if (objectUrl !== url) window.URL.revokeObjectURL(objectUrl);
            return;
          }
          record.objectUrl = objectUrl;
          // IntersectionObserver already decided that this face is close to
          // view. Switch the actual asset request to eager so Chromium does
          // not keep a still-hidden lazy image at complete=false forever.
          // The manager remains lazy at the face level because load() is only
          // reached after that observer (or an explicit eager observe).
          record.image.loading = "eager";
          record.image.src = objectUrl;
          await waitForImage(window, record.image);
          if (!isCurrent(record)) return;
          mark(record, "loaded", "");
          return;
        } catch (error) {
          if (error?.name === "AbortError" || !isCurrent(record)) return;
          if (record.objectUrl && objectUrls.has(record.objectUrl)) {
            window.URL.revokeObjectURL(record.objectUrl);
            objectUrls.delete(record.objectUrl);
            record.objectUrl = null;
            record.image.removeAttribute("src");
          }
          lastError = error;
          if (attempt < MAX_ATTEMPTS - 1 && error?.retryable !== false) {
            await delay(RETRY_DELAYS[attempt]);
            continue;
          }
          break;
        }
      }
      if (!isCurrent(record)) return;
      mark(
        record,
        pendingExhausted || lastError?.pending ? "pending" : "unavailable",
        pendingExhausted || lastError?.pending ? copy.pending : copy.unavailable,
      );
      if (pendingExhausted) schedulePendingRetry(record);
    })();
    await record.promise;
    return record.promise;
  }

  function observe(face, card, observeOptions = {}) {
    if (!face || !card) return;
    const image = face.querySelector(".static-card-face-image");
    const fallback = face.querySelector(".static-card-face-fallback");
    const status = face.querySelector(".static-card-face-status");
    const id = cardId(card);
    if (!image || !fallback || !id) return;
    const previous = records.get(face);
    if (previous) {
      previous.cancelled = true;
      previous.controller?.abort();
      clearRetryTimer(previous);
    }
    const controller = typeof window?.AbortController === "function" ? new window.AbortController() : null;
    const record = {
      face,
      image,
      fallback,
      status,
      card,
      id,
      locale,
      generation,
      sequence: ++sequence,
      controller,
      cancelled: false,
      objectUrl: null,
      retryTimer: null,
      promise: null,
    };
    records.set(face, record);
    setState(record, "waiting", copy.loading);
    if (observeOptions.eager || !observer) {
      void load(record);
    } else {
      observer.observe(face);
    }
  }

  if (window && typeof window.IntersectionObserver === "function") {
    observer = new window.IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        const record = records.get(entry.target);
        if (record) void load(record);
      });
    }, { rootMargin: "240px 0px" });
  }

  function release() {
    generation += 1;
    observer?.disconnect();
    records.forEach((record) => {
      record.cancelled = true;
      record.controller?.abort();
      clearRetryTimer(record);
      if (record.objectUrl && objectUrls.has(record.objectUrl)) {
        window.URL.revokeObjectURL(record.objectUrl);
        objectUrls.delete(record.objectUrl);
      }
    });
    objectUrls.forEach((url) => window.URL.revokeObjectURL(url));
    objectUrls.clear();
    records.clear();
  }

  return {
    document,
    locale,
    observe,
    release,
  };
}

export { cardId, cardName, cardRules, renderAssetUrl };
