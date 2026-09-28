import { createStaticCardFace, createStaticCardFaceManager } from "./card_face.js";

/* Card catalog composition root.  It owns only catalog state and never
 * reaches into the match GUI modules. */

const PAGE_SIZE = 48;
const CATALOG_CLASSES = [
  "NEUTRAL", "DRUID", "HUNTER", "MAGE", "PALADIN", "PRIEST",
  "ROGUE", "SHAMAN", "WARLOCK", "WARRIOR", "DEMONHUNTER",
];
const IMAGE_ATTEMPTS = 6;
const IMAGE_RETRY_DELAYS = [250, 750, 1500, 3000, 5000];

const refs = {
  app: document.getElementById("catalog-app"),
  back: document.getElementById("catalog-back"),
  eyebrow: document.getElementById("catalog-eyebrow"),
  title: document.getElementById("catalog-title"),
  subtitle: document.getElementById("catalog-subtitle"),
  languageLabel: document.getElementById("catalog-language-label"),
  localeButtons: [
    document.getElementById("catalog-locale-zhCN"),
    document.getElementById("catalog-locale-enUS"),
  ],
  filterEyebrow: document.getElementById("catalog-filter-eyebrow"),
  filterTitle: document.getElementById("catalog-filter-title"),
  search: document.getElementById("catalog-search"),
  searchLabel: document.getElementById("catalog-search-label"),
  searchHint: document.getElementById("catalog-search-hint"),
  clearSearch: document.getElementById("catalog-clear-search"),
  set: document.getElementById("catalog-set"),
  setLabel: document.getElementById("catalog-set-label"),
  class: document.getElementById("catalog-class"),
  classLabel: document.getElementById("catalog-class-label"),
  resultsEyebrow: document.querySelector(".catalog-results .eyebrow"),
  resultsTitle: document.getElementById("catalog-results-title"),
  resultCount: document.getElementById("catalog-result-count"),
  status: document.getElementById("catalog-status"),
  error: document.getElementById("catalog-error"),
  errorMessage: document.getElementById("catalog-error-message"),
  retry: document.getElementById("catalog-retry"),
  grid: document.getElementById("catalog-grid"),
  empty: document.getElementById("catalog-empty"),
  emptyTitle: document.getElementById("catalog-empty-title"),
  emptyCopy: document.getElementById("catalog-empty-copy"),
  pagination: document.getElementById("catalog-pagination"),
  previous: document.getElementById("catalog-page-previous"),
  pageLabel: document.getElementById("catalog-page-label"),
  next: document.getElementById("catalog-page-next"),
  dialog: document.getElementById("catalog-dialog"),
  dialogClose: document.getElementById("catalog-dialog-close"),
  detailArt: document.getElementById("catalog-detail-art"),
  detailPlaceholder: document.getElementById("catalog-detail-placeholder"),
  detailImage: document.getElementById("catalog-detail-image"),
  detailEyebrow: document.getElementById("catalog-detail-eyebrow"),
  detailName: document.getElementById("catalog-detail-name"),
  detailId: document.getElementById("catalog-detail-id"),
  detailBadges: document.getElementById("catalog-detail-badges"),
  scriptNote: document.getElementById("catalog-script-note"),
  detailStats: document.getElementById("catalog-detail-stats"),
  rulesTitle: document.getElementById("catalog-rules-title"),
  detailText: document.getElementById("catalog-detail-text"),
};

const state = {
  locale: initialLocale(),
  filters: { set: "BASIC", class: "NEUTRAL", query: "", page: 1 },
  items: [],
  total: 0,
  pageSize: PAGE_SIZE,
  sets: [],
  classes: [],
  requestNumber: 0,
  detailRequestNumber: 0,
  catalogController: null,
  imageUrls: new Set(),
  imagePromises: new WeakMap(),
  imageSequence: 0,
  detailImageGeneration: 0,
  detailImageUrl: null,
  searchTimer: null,
  previousFocus: null,
  detailCard: null,
  cardFaceManager: null,
};

function i18n() {
  return globalThis.FireplaceI18n;
}

function t(key, variables) {
  const dictionary = i18n();
  if (dictionary && typeof dictionary.t === "function") {
    return dictionary.t(key, variables, state.locale);
  }
  return key;
}

function normalizeLocale(value) {
  const dictionary = i18n();
  if (dictionary && typeof dictionary.normalizeLocale === "function") {
    return dictionary.normalizeLocale(value);
  }
  return value === "enUS" ? "enUS" : "zhCN";
}

function initialLocale() {
  try {
    return normalizeLocale(localStorage.getItem("fireplace.locale") || "zhCN");
  } catch (_error) {
    return "zhCN";
  }
}

function storeLocale(locale) {
  try {
    localStorage.setItem("fireplace.locale", locale);
  } catch (_error) {
    // Private browsing should not make the catalog unusable.
  }
}

function text(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function optionValue(raw) {
  if (typeof raw === "string" || typeof raw === "number") {
    return { value: String(raw), label: String(raw) };
  }
  if (!raw || typeof raw !== "object") return null;
  const value = text(raw.id);
  if (!value) return null;
  const label = text(raw.label, value);
  return { value, label };
}

function optionList(raw) {
  if (Array.isArray(raw)) return raw.map(optionValue).filter(Boolean);
  return [];
}

function arrayValue(value) {
  if (Array.isArray(value)) return value;
  return [];
}

function optionLabel(options, value) {
  const match = optionList(options).find((option) => option.value === value);
  return match ? match.label : value;
}

function enumLabel(group, value) {
  const stableValue = text(value).toUpperCase();
  if (!stableValue) return "";
  const localized = t(`catalog.${group}.${stableValue}`);
  return localized === `catalog.${group}.${stableValue}` ? stableValue : localized;
}

function normalizeCard(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const id = text(source.id);
  const name = text(source.name, id || t("unknownCard"));
  const rulesText = text(source.text);
  const setId = text(source.card_set);
  const type = text(source.type);
  const catalogSetId = text(source.catalog_set, type === "HERO" && setId === "BASIC" ? "HEROES" : setId);
  const setName = optionLabel(state.sets, setId);
  const catalogSetName = optionLabel(state.sets, catalogSetId || setId);
  const classValues = arrayValue(source.classes).map((value) => text(value)).filter(Boolean);
  const className = classValues.map((value) => optionLabel(state.classes, value)).join(state.locale === "enUS" ? ", " : "、");
  const rarity = text(source.rarity);
  const collectible = source.collectible;
  const hasPythonScript = typeof source.has_python_script === "boolean" ? source.has_python_script : null;
  return {
    raw: source,
    id,
    name,
    rulesText,
    setId,
    setName,
    catalogSetId,
    catalogSetName,
    isStartingHero: catalogSetId === "HEROES",
    classValues,
    className,
    type,
    rarity,
    collectible: typeof collectible === "boolean" ? collectible : null,
    cost: source.cost,
    attack: source.attack,
    health: source.health,
    durability: source.durability,
    hasPythonScript,
  };
}

function normalizeDetail(payload, fallback) {
  if (!payload || typeof payload !== "object") return fallback;
  const card = payload.card && typeof payload.card === "object" ? payload.card : payload;
  return normalizeCard({ ...fallback.raw, ...card });
}

function imageUrl(cardId, locale = state.locale, kind = "art") {
  const assetKind = kind === "render" ? "render" : "art";
  return `/catalog/assets/${assetKind}/${encodeURIComponent(cardId)}?locale=${encodeURIComponent(locale)}`;
}

function releaseDetailImage() {
  if (!state.detailImageUrl) return;
  URL.revokeObjectURL(state.detailImageUrl);
  state.imageUrls.delete(state.detailImageUrl);
  state.detailImageUrl = null;
}

function placeholderFor(image) {
  return image.parentElement && image.parentElement.querySelector(".catalog-image-placeholder");
}

function markImageUnavailable(image, pending = false) {
  image.hidden = true;
  image.dataset.imageState = pending ? "pending" : "unavailable";
  const placeholder = placeholderFor(image);
  if (placeholder) {
    placeholder.hidden = false;
    placeholder.textContent = t(pending ? "catalog.imagePending" : "catalog.imageUnavailable");
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function loadImage(image, cardId, locale = state.locale) {
  if (!image || !cardId || image.dataset.imageState === "loaded") return;
  const assetKind = image.dataset.assetKind === "render" ? "render" : "art";
  const key = `${cardId}\u0000${locale}\u0000${assetKind}\u0000${image.dataset.loadGeneration || ""}`;
  const existing = state.imagePromises.get(image);
  if (existing && existing.key === key) return existing.promise;
  const token = String(++state.imageSequence);
  image.dataset.imageRequest = token;
  const record = { key, promise: null };
  const promise = (async () => {
    image.dataset.imageState = "loading";
    const placeholder = placeholderFor(image);
    if (placeholder) {
      placeholder.hidden = false;
      placeholder.textContent = image === refs.detailImage ? t("catalog.loadingCard") : t("catalog.loadingImage");
    }
    let lastError = null;
    for (let attempt = 0; attempt < IMAGE_ATTEMPTS; attempt += 1) {
      try {
        const response = await fetch(imageUrl(cardId, locale, assetKind), { cache: "no-store" });
        if (response.status === 202) {
          if (attempt < IMAGE_ATTEMPTS - 1) {
            await wait(IMAGE_RETRY_DELAYS[attempt]);
            continue;
          }
          const pendingError = new Error("asset still pending");
          pendingError.retryable = true;
          pendingError.pending = true;
          throw pendingError;
        }
        if (!response.ok) {
          const responseError = new Error(`HTTP ${response.status}`);
          responseError.retryable = response.status >= 500 || response.status === 408 || response.status === 429;
          throw responseError;
        }
        if (response.headers?.get?.("X-Asset-Placeholder") === "1") {
          const placeholderError = new Error("asset placeholder");
          placeholderError.pending = true;
          placeholderError.retryable = false;
          throw placeholderError;
        }
        const blob = await response.blob();
        if (!blob.size) throw new Error("empty asset response");
        const objectUrl = URL.createObjectURL(blob);
        if (!image.isConnected || image.dataset.imageRequest !== token) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        if (image === refs.detailImage) {
          releaseDetailImage();
          state.detailImageUrl = objectUrl;
        }
        state.imageUrls.add(objectUrl);
        image.src = objectUrl;
        image.dataset.imageState = "loaded";
        image.hidden = false;
        if (placeholder) placeholder.hidden = true;
        return;
      } catch (error) {
        lastError = error;
        if (attempt < IMAGE_ATTEMPTS - 1 && error.retryable !== false) {
          await wait(IMAGE_RETRY_DELAYS[attempt]);
        } else {
          break;
        }
      }
    }
    if (image.dataset.imageRequest === token) markImageUnavailable(image, Boolean(lastError && lastError.pending));
  })();
  record.promise = promise;
  state.imagePromises.set(image, record);
  try {
    await promise;
  } finally {
    if (state.imagePromises.get(image) === record) state.imagePromises.delete(image);
  }
}

function createNode(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function renderCard(card) {
  const button = createNode("button", "catalog-card");
  button.type = "button";
  button.dataset.cardId = card.id;
  button.dataset.testid = "catalog-card";
  if (card.catalogSetId) button.dataset.catalogSet = card.catalogSetId;
  if (typeof card.hasPythonScript === "boolean") button.dataset.hasPythonScript = String(card.hasPythonScript);
  button.setAttribute("aria-label", t("catalog.openDetail", { value: card.name }));
  button.addEventListener("click", () => openDetail(card, button));

  const face = createStaticCardFace(card, {
    locale: state.locale,
    copy: {
      cost: t("catalog.cost"),
      attack: t("catalog.attack"),
      health: t("catalog.health"),
      durability: t("durability"),
      rules: t("catalog.rules"),
      noRules: t("catalog.noRules"),
      loading: t("catalog.loadingImage"),
      pending: t("catalog.imagePending"),
      unavailable: t("catalog.imageUnavailable"),
      cardImage: t("catalog.cardImage"),
      unknownCard: t("unknownCard"),
    },
  });
  button.append(face);
  if (face.dataset.descriptionId) button.setAttribute("aria-describedby", face.dataset.descriptionId);

  const copy = createNode("span", "catalog-card-copy");
  copy.append(createNode("strong", "catalog-card-name", card.name));
  const metadata = createNode("span", "catalog-card-meta");
  const set = createNode("span", "catalog-card-set", card.catalogSetName || card.catalogSetId || card.setName || card.setId);
  const className = createNode("span", "catalog-card-class", card.className || "—");
  metadata.append(set, className);
  copy.append(metadata);
  if (card.collectible === false) copy.append(createNode("span", "catalog-card-badge", t("catalog.nonCollectible")));
  if (typeof card.hasPythonScript === "boolean") {
    const scriptClass = card.hasPythonScript ? "is-script-present" : "is-script-missing";
    const scriptBadge = createNode(
      "span",
      `catalog-card-badge catalog-script-badge ${scriptClass}`,
      t(card.hasPythonScript ? "catalog.pythonScriptYes" : "catalog.pythonScriptNo"),
    );
    scriptBadge.setAttribute("aria-label", `${t("catalog.pythonScript")}: ${scriptBadge.textContent}`);
    copy.append(scriptBadge);
  }
  button.append(copy);
  return button;
}

function renderCards() {
  state.cardFaceManager?.release();
  state.cardFaceManager = createStaticCardFaceManager({
    locale: state.locale,
    copy: {
      cost: t("catalog.cost"),
      attack: t("catalog.attack"),
      health: t("catalog.health"),
      durability: t("durability"),
      rules: t("catalog.rules"),
      noRules: t("catalog.noRules"),
      loading: t("catalog.loadingImage"),
      pending: t("catalog.imagePending"),
      unavailable: t("catalog.imageUnavailable"),
      cardImage: t("catalog.cardImage"),
      unknownCard: t("unknownCard"),
    },
  });
  refs.grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  state.items.forEach((card) => fragment.append(renderCard(card)));
  refs.grid.append(fragment);
  refs.grid.querySelectorAll(".static-card-face").forEach((face) => {
    const card = state.items.find((item) => item.id === face.dataset.cardId);
    if (card) state.cardFaceManager.observe(face, card);
  });
  const empty = state.items.length === 0;
  refs.grid.hidden = empty;
  refs.empty.hidden = !empty;
}

function renderSetOptions(select, options, selected) {
  const normalized = optionList(options);
  select.replaceChildren();
  if (!normalized.length) normalized.push({ value: selected, label: selected });
  normalized.forEach((option) => select.append(new Option(option.label, option.value)));
  select.value = selected;
}

function renderMetadata() {
  renderSetOptions(refs.set, state.sets, state.filters.set);
  refs.class.replaceChildren(...CATALOG_CLASSES.map((value) => new Option(t(`class.${value}`), value)));
  refs.class.value = state.filters.class;
}

function totalPages() {
  return Math.max(1, Math.ceil(state.total / Math.max(1, state.pageSize)));
}

function scrollToCatalog() {
  refs.app.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "start",
  });
}

function renderPagination() {
  const pages = totalPages();
  const visible = state.total > 0 && pages > 1;
  refs.pagination.hidden = !visible;
  refs.previous.disabled = state.filters.page <= 1;
  refs.next.disabled = state.filters.page >= pages;
  refs.pageLabel.textContent = t("catalog.page", { value: state.filters.page, total: pages });
}

function renderResultSummary() {
  refs.resultCount.textContent = t("catalog.results", { value: state.total });
  refs.status.textContent = "";
}

function renderStaticCopy() {
  document.documentElement.lang = state.locale === "enUS" ? "en" : "zh-CN";
  document.title = `Fireplace · ${t("catalog.title")}`;
  const description = document.querySelector("meta[name=description]");
  if (description) description.content = t("catalog.subtitle");
  refs.back.querySelector("#catalog-back-label").textContent = t("catalog.back");
  refs.eyebrow.textContent = t("catalog.eyebrow");
  refs.title.textContent = t("catalog.title");
  refs.subtitle.textContent = t("catalog.subtitle");
  refs.languageLabel.textContent = t("catalog.language");
  refs.filterEyebrow.textContent = t("catalog.filters");
  refs.filterTitle.textContent = t("catalog.filterTitle");
  refs.searchLabel.textContent = t("catalog.searchLabel");
  refs.search.placeholder = t("catalog.searchPlaceholder");
  refs.searchHint.textContent = t("catalog.searchHint");
  refs.clearSearch.setAttribute("aria-label", t("catalog.clearSearch"));
  refs.setLabel.textContent = t("catalog.setLabel");
  refs.classLabel.textContent = t("catalog.classLabel");
  refs.resultsEyebrow.textContent = t("catalog.collection");
  refs.resultsTitle.textContent = t("catalog.resultsTitle");
  refs.emptyTitle.textContent = t("catalog.noResults");
  refs.emptyCopy.textContent = t("catalog.emptyFilter");
  refs.retry.textContent = t("catalog.retry");
  refs.previous.textContent = t("catalog.previous");
  refs.next.textContent = t("catalog.next");
  refs.detailEyebrow.textContent = t("catalog.detailEyebrow");
  refs.dialogClose.setAttribute("aria-label", t("catalog.close"));
  refs.rulesTitle.textContent = t("catalog.rules");
  refs.scriptNote.textContent = t("catalog.pythonScriptCaveat");
  if (!state.detailCard) refs.detailText.textContent = t("catalog.noRules");
  refs.localeButtons.forEach((button) => {
    const selected = button.dataset.locale === state.locale;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  renderMetadata();
  renderPagination();
}

function setLoading(value) {
  refs.grid.setAttribute("aria-busy", value ? "true" : "false");
  refs.status.textContent = value ? t("catalog.loading") : "";
  if (value) {
    refs.empty.hidden = true;
    refs.error.hidden = true;
  }
}

function errorMessage(error) {
  return error && error.message ? error.message : t("unknownError");
}

async function requestJson(url, signal) {
  const response = await fetch(url, { cache: "no-store", signal, headers: { Accept: "application/json" } });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    throw new Error(payload && payload.error ? String(payload.error) : `HTTP ${response.status}`);
  }
  return payload || {};
}

function catalogUrl() {
  const query = new URLSearchParams({
    locale: state.locale,
    scope: "collectible",
    class: state.filters.class,
    sort: "cost",
    page: String(state.filters.page),
    page_size: String(PAGE_SIZE),
  });
  if (state.filters.set) query.set("set", state.filters.set);
  if (state.filters.query) query.set("q", state.filters.query);
  return `/api/catalog?${query.toString()}`;
}

async function loadCatalog() {
  const requestNumber = ++state.requestNumber;
  if (state.catalogController) state.catalogController.abort();
  state.catalogController = new AbortController();
  setLoading(true);
  try {
    const payload = await requestJson(catalogUrl(), state.catalogController.signal);
    if (requestNumber !== state.requestNumber) return;
    const rawItems = Array.isArray(payload.items) ? payload.items : [];
    state.total = Number.isFinite(Number(payload.total)) ? Number(payload.total) : rawItems.length;
    state.pageSize = Number.isFinite(Number(payload.page_size)) && Number(payload.page_size) > 0 ? Number(payload.page_size) : PAGE_SIZE;
    state.filters.page = Number.isFinite(Number(payload.page)) && Number(payload.page) > 0 ? Number(payload.page) : state.filters.page;
    if (payload.sets !== undefined) state.sets = payload.sets;
    if (payload.classes !== undefined) state.classes = payload.classes;
    const availableSets = optionList(state.sets);
    if (availableSets.length && !availableSets.some((option) => option.value === state.filters.set)) {
      state.filters.set = (availableSets.find((option) => option.value !== "HEROES") || availableSets[0]).value;
      state.filters.page = 1;
      void loadCatalog();
      return;
    }
    state.items = rawItems.map(normalizeCard).filter((card) => card.id);
    renderMetadata();
    renderCards();
    renderResultSummary();
    renderPagination();
    refs.error.hidden = true;
  } catch (error) {
    if (error && error.name === "AbortError") return;
    if (requestNumber !== state.requestNumber) return;
    state.cardFaceManager?.release();
    state.cardFaceManager = null;
    refs.grid.replaceChildren();
    refs.grid.hidden = true;
    refs.empty.hidden = true;
    refs.error.hidden = false;
    refs.errorMessage.textContent = t("catalog.loadError", { message: errorMessage(error) });
    refs.status.textContent = "";
  } finally {
    if (requestNumber === state.requestNumber) setLoading(false);
  }
}

function updateClearButton() {
  refs.clearSearch.hidden = !state.filters.query;
}

function scheduleSearch() {
  state.filters.query = refs.search.value.trim();
  updateClearButton();
  if (state.searchTimer !== null) window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(() => {
    state.filters.page = 1;
    void loadCatalog();
  }, 280);
}

function submitSearchNow() {
  if (state.searchTimer !== null) window.clearTimeout(state.searchTimer);
  state.searchTimer = null;
  state.filters.query = refs.search.value.trim();
  state.filters.page = 1;
  updateClearButton();
  void loadCatalog();
}

function setLocale(value) {
  const next = normalizeLocale(value);
  if (next === state.locale) return;
  if (state.detailCard || refs.dialog.open) closeDetail();
  state.cardFaceManager?.release();
  state.cardFaceManager = null;
  state.locale = next;
  storeLocale(next);
  renderStaticCopy();
  void loadCatalog();
}

function appendDetailBadge(label, value, className = "") {
  if (!text(value).trim()) return;
  const badge = createNode("span", `catalog-detail-badge${className ? ` ${className}` : ""}`);
  if (text(label).trim()) badge.append(createNode("strong", "catalog-detail-badge-label", label));
  badge.append(document.createTextNode(text(value)));
  refs.detailBadges.append(badge);
}

function appendStat(label, value) {
  if (!text(value).trim()) return;
  const term = createNode("dt", "catalog-stat-label", label);
  const description = createNode("dd", "catalog-stat-value", value);
  refs.detailStats.append(term, description);
}

function renderDetail(card) {
  state.detailCard = card;
  releaseDetailImage();
  refs.detailName.textContent = card.name;
  refs.detailId.textContent = `${t("catalog.cardId")}: ${card.id}`;
  refs.detailBadges.replaceChildren();
  appendDetailBadge(t("catalog.set"), card.catalogSetName || card.catalogSetId || card.setName || card.setId);
  if (card.isStartingHero && card.setId && card.setId !== card.catalogSetId) {
    appendDetailBadge(t("catalog.originalSet"), card.setName || card.setId, "is-muted");
  }
  appendDetailBadge(t("catalog.class"), card.className);
  const collectionLabel = card.collectible === false
    ? t("catalog.nonCollectible")
    : card.collectible === true ? t("catalog.collectible") : "";
  if (collectionLabel) appendDetailBadge("", collectionLabel, card.collectible === false ? "is-muted" : "is-collectible");
  if (typeof card.hasPythonScript === "boolean") {
    const scriptClass = card.hasPythonScript ? "is-script-present" : "is-script-missing";
    appendDetailBadge(
      t("catalog.pythonScript"),
      t(card.hasPythonScript ? "catalog.pythonScriptYes" : "catalog.pythonScriptNo"),
      scriptClass,
    );
    refs.scriptNote.hidden = false;
    refs.scriptNote.textContent = t("catalog.pythonScriptCaveat");
  } else {
    refs.scriptNote.hidden = true;
    refs.scriptNote.textContent = "";
  }
  refs.detailStats.replaceChildren();
  appendStat(t("catalog.cardType"), enumLabel("type", card.type));
  appendStat(t("catalog.rarity"), enumLabel("rarity", card.rarity));
  appendStat(t("catalog.cost"), card.cost);
  appendStat(t("catalog.attack"), card.attack);
  appendStat(t("catalog.health"), card.health);
  appendStat(t("durability"), card.durability);
  refs.detailText.textContent = card.rulesText || t("catalog.noRules");
  refs.detailImage.alt = `${card.name} · ${t("catalog.cardImage")}`;
  refs.detailPlaceholder.textContent = t("catalog.loadingCard");
  refs.detailPlaceholder.hidden = false;
  refs.detailImage.hidden = true;
  refs.detailImage.dataset.assetKind = "render";
  refs.detailImage.dataset.imageState = "waiting";
  state.detailImageGeneration += 1;
  refs.detailImage.dataset.loadGeneration = String(state.detailImageGeneration);
  void loadImage(refs.detailImage, card.id, state.locale);
}

async function openDetail(card, source) {
  state.previousFocus = source || document.activeElement;
  const requestNumber = ++state.detailRequestNumber;
  renderDetail(card);
  if (typeof refs.dialog.showModal === "function") {
    if (!refs.dialog.open) refs.dialog.showModal();
  } else {
    refs.dialog.setAttribute("open", "");
  }
  refs.dialogClose.focus();
  try {
    const payload = await requestJson(`/api/catalog/cards/${encodeURIComponent(card.id)}?locale=${encodeURIComponent(state.locale)}`);
    if (requestNumber !== state.detailRequestNumber) return;
    renderDetail(normalizeDetail(payload, card));
  } catch (error) {
    if (requestNumber !== state.detailRequestNumber || (error && error.name === "AbortError")) return;
    refs.detailText.textContent = card.rulesText || t("catalog.noRules");
  }
}

function closeDetail() {
  state.detailRequestNumber += 1;
  if (refs.dialog.open && typeof refs.dialog.close === "function") refs.dialog.close();
  else refs.dialog.removeAttribute("open");
  state.detailImageGeneration += 1;
  refs.detailImage.dataset.loadGeneration = String(state.detailImageGeneration);
  refs.detailImage.dataset.imageRequest = "";
  releaseDetailImage();
  refs.detailImage.hidden = true;
  refs.detailImage.dataset.imageState = "waiting";
  refs.detailPlaceholder.hidden = false;
  if (state.previousFocus && typeof state.previousFocus.focus === "function") state.previousFocus.focus();
  state.previousFocus = null;
  state.detailCard = null;
}

function bindEvents() {
  refs.localeButtons.forEach((button) => button.addEventListener("click", () => setLocale(button.dataset.locale)));
  refs.search.addEventListener("input", scheduleSearch);
  refs.search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submitSearchNow();
    }
  });
  refs.clearSearch.addEventListener("click", () => {
    refs.search.value = "";
    submitSearchNow();
    refs.search.focus();
  });
  refs.set.addEventListener("change", () => {
    state.filters.set = refs.set.value;
    state.filters.page = 1;
    void loadCatalog();
  });
  refs.class.addEventListener("change", () => {
    if (!CATALOG_CLASSES.includes(refs.class.value)) return;
    state.filters.class = refs.class.value;
    state.filters.page = 1;
    void loadCatalog();
  });
  refs.previous.addEventListener("click", () => {
    if (state.filters.page <= 1) return;
    state.filters.page -= 1;
    void loadCatalog();
    scrollToCatalog();
  });
  refs.next.addEventListener("click", () => {
    if (state.filters.page >= totalPages()) return;
    state.filters.page += 1;
    void loadCatalog();
    scrollToCatalog();
  });
  refs.retry.addEventListener("click", () => void loadCatalog());
  refs.dialogClose.addEventListener("click", closeDetail);
  refs.dialog.addEventListener("click", (event) => {
    if (event.target && event.target.dataset.dialogClose === "true") closeDetail();
  });
  refs.dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDetail();
  });
  refs.dialog.addEventListener("close", () => {
    state.detailCard = null;
  });
}

function init() {
  bindEvents();
  renderStaticCopy();
  updateClearButton();
  void loadCatalog();
}

init();
