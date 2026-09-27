import { announceAccountChange } from "./account_session.js";

/* Account entry point.  Passwords are submitted only to the server and are
 * never copied to browser storage or placed in a URL. */

const COPY = {
  zhCN: {
    back: "返回开始界面",
    title: "账号",
    subtitle: "登录后访问你的卡组、竞技场和对战。",
    language: "界面语言",
    loginTab: "登录",
    registerTab: "注册",
    username: "用户名",
    usernameHint: "使用 1 到 64 个字符。",
    password: "密码",
    passwordHint: "至少 8 个字符。",
    confirmPassword: "确认密码",
    loginSubmit: "登录",
    registerSubmit: "创建账号",
    signedIn: "已登录",
    currentUser: "当前账号",
    continue: "继续",
    logout: "退出登录",
    importLegacy: "导入旧数据",
    importLegacyHint: "检测到账号创建前的本机卡组或竞技场数据。",
    importLegacyConfirm: "将旧的本机卡组和竞技场进度导入当前账号吗？原始文件会保留。",
    importLegacyDone: "旧数据已导入当前账号。",
    importLegacyFailed: "旧数据导入失败：{message}",
    footer: "账号数据保存在本机服务器中。",
    usernameRequired: "请输入用户名。",
    passwordRequired: "请输入密码。",
    passwordShort: "密码至少需要 8 个字符。",
    passwordMismatch: "两次输入的密码不一致。",
    requestFailed: "请求失败：{message}",
    network: "无法连接本机账号服务。",
    loggingIn: "正在登录……",
    registering: "正在创建账号……",
    loggingOut: "正在退出……",
    importing: "正在导入旧数据……",
  },
  enUS: {
    back: "Back to start",
    title: "Account",
    subtitle: "Sign in to access your decks, Arena runs, and matches.",
    language: "Language",
    loginTab: "Log in",
    registerTab: "Register",
    username: "Username",
    usernameHint: "Use 1 to 64 characters.",
    password: "Password",
    passwordHint: "At least 8 characters.",
    confirmPassword: "Confirm password",
    loginSubmit: "Log in",
    registerSubmit: "Create account",
    signedIn: "Signed in",
    currentUser: "Current account",
    continue: "Continue",
    logout: "Log out",
    importLegacy: "Import old data",
    importLegacyHint: "Saved decks or Arena progress from before accounts were added was found on this server.",
    importLegacyConfirm: "Import the old local decks and Arena progress into this account? The original files will be kept.",
    importLegacyDone: "Old data was imported into this account.",
    importLegacyFailed: "Unable to import old data: {message}",
    footer: "Account data is stored on this local server.",
    usernameRequired: "Enter a username.",
    passwordRequired: "Enter a password.",
    passwordShort: "Password must be at least 8 characters.",
    passwordMismatch: "The passwords do not match.",
    requestFailed: "Request failed: {message}",
    network: "The local account service is unavailable.",
    loggingIn: "Signing in…",
    registering: "Creating account…",
    loggingOut: "Signing out…",
    importing: "Importing old data…",
  },
};

const refs = {
  app: document.getElementById("account-app"),
  form: document.getElementById("account-form"),
  tabs: [...document.querySelectorAll("[data-mode]")],
  localeButtons: [...document.querySelectorAll("[data-locale]")],
  copyNodes: [...document.querySelectorAll("[data-copy]")],
  username: document.getElementById("account-username"),
  password: document.getElementById("account-password"),
  confirmField: document.getElementById("account-confirm-field"),
  confirmPassword: document.getElementById("account-confirm-password"),
  submit: document.getElementById("account-submit"),
  status: document.getElementById("account-status"),
  error: document.getElementById("account-error"),
  formPanel: document.getElementById("account-form"),
  sessionPanel: document.getElementById("account-session-panel"),
  sessionUsername: document.getElementById("account-session-username"),
  continue: document.getElementById("account-continue"),
  logout: document.getElementById("account-logout"),
  importLegacy: document.getElementById("account-import-legacy"),
  importHint: document.getElementById("account-import-hint"),
};

const model = {
  locale: readLocale(),
  mode: "login",
  account: null,
  legacyAvailable: false,
  busy: false,
};

function text(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  return fallback;
}

function t(key, variables = {}) {
  const value = COPY[model.locale]?.[key] ?? COPY.zhCN[key] ?? key;
  return String(value).replace(/\{(\w+)\}/g, (_match, name) => String(variables[name] ?? ""));
}

function readLocale() {
  try {
    return localStorage.getItem("fireplace.locale") === "enUS" ? "enUS" : "zhCN";
  } catch (_error) {
    return "zhCN";
  }
}

function storeLocale(locale) {
  try { localStorage.setItem("fireplace.locale", locale); } catch (_error) { /* private mode */ }
}

function safeNextPath() {
  const raw = new URLSearchParams(window.location.search).get("next") || "/";
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\") || raw.includes("\u0000")) return "/";
  try {
    const parsed = new URL(raw, window.location.origin);
    if (parsed.origin !== window.location.origin) return "/";
    const value = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    return value === "/account" || value.startsWith("/account?") ? "/" : value || "/";
  } catch (_error) {
    return "/";
  }
}

function hasExplicitNext() {
  return new URLSearchParams(window.location.search).has("next");
}

function setStatus(message = "") {
  refs.status.textContent = message;
}

function setError(message = "") {
  refs.error.textContent = message;
  refs.error.hidden = !message;
}

function setBusy(value) {
  model.busy = Boolean(value);
  refs.tabs.forEach((tab) => { tab.disabled = model.busy; });
  refs.localeButtons.forEach((button) => { button.disabled = model.busy; });
  refs.username.disabled = model.busy;
  refs.password.disabled = model.busy;
  refs.confirmPassword.disabled = model.busy;
  refs.submit.disabled = model.busy;
  refs.logout.disabled = model.busy;
  refs.importLegacy.disabled = model.busy;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    cache: "no-store",
  });
  let payload = {};
  try { payload = await response.json(); } catch (_error) { /* empty response */ }
  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || payload?.error || `${response.status}`;
    const error = new Error(text(message, `${response.status}`));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function accountFromPayload(payload) {
  const account = payload?.account;
  if (!payload?.authenticated || !account || typeof account !== "object") return null;
  const username = text(account.username).trim();
  const id = text(account.id).trim();
  return username && id ? { id, username } : null;
}

function renderCopy() {
  refs.copyNodes.forEach((node) => {
    node.textContent = t(node.dataset.copy);
  });
  document.documentElement.lang = model.locale === "enUS" ? "en" : "zh-CN";
  document.title = `Fireplace · ${t("title")}`;
  refs.localeButtons.forEach((button) => {
    const selected = button.dataset.locale === model.locale;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderMode() {
  const registering = model.mode === "register";
  refs.tabs.forEach((tab) => {
    const selected = tab.dataset.mode === model.mode;
    tab.classList.toggle("is-selected", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  refs.confirmField.hidden = !registering;
  refs.confirmPassword.required = registering;
  refs.password.autocomplete = registering ? "new-password" : "current-password";
  refs.submit.textContent = t(registering ? "registerSubmit" : "loginSubmit");
}

function renderSession() {
  const authenticated = Boolean(model.account);
  refs.formPanel.hidden = authenticated;
  refs.sessionPanel.hidden = !authenticated;
  refs.tabs.forEach((tab) => { tab.hidden = authenticated; });
  if (!authenticated) return;
  refs.sessionUsername.textContent = model.account.username;
  refs.continue.href = safeNextPath();
  refs.importLegacy.hidden = !model.legacyAvailable;
  refs.importHint.hidden = !model.legacyAvailable;
}

function render() {
  renderCopy();
  renderMode();
  renderSession();
}

function errorMessage(error) {
  return error?.message || t("network");
}

async function loadSession() {
  try {
    const payload = await request("/api/account/session");
    model.account = accountFromPayload(payload);
    model.legacyAvailable = payload?.legacy_available === true;
    renderSession();
    if (model.account && hasExplicitNext()) {
      window.location.replace(safeNextPath());
      return true;
    }
  } catch (error) {
    model.account = null;
    model.legacyAvailable = false;
    setError(t("requestFailed", { message: errorMessage(error) }));
  }
  return false;
}

function validateForm() {
  const username = text(refs.username.value).trim();
  const password = text(refs.password.value);
  if (!username) return { error: t("usernameRequired") };
  if (!password) return { error: t("passwordRequired") };
  if (password.length < 8) return { error: t("passwordShort") };
  if (model.mode === "register" && password !== text(refs.confirmPassword.value)) {
    return { error: t("passwordMismatch") };
  }
  return { username, password };
}

async function submitForm(event) {
  event.preventDefault();
  if (model.busy) return;
  setError("");
  const values = validateForm();
  if (values.error) {
    setError(values.error);
    return;
  }
  setBusy(true);
  setStatus(t(model.mode === "register" ? "registering" : "loggingIn"));
  try {
    const path = model.mode === "register" ? "/api/account/register" : "/api/account/login";
    const payload = await request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: values.username, password: values.password }),
    });
    model.account = accountFromPayload(payload);
    model.legacyAvailable = payload?.legacy_available === true;
    announceAccountChange();
    refs.password.value = "";
    refs.confirmPassword.value = "";
    renderSession();
    if (model.account) window.location.assign(safeNextPath());
  } catch (error) {
    setError(t("requestFailed", { message: errorMessage(error) }));
  } finally {
    setBusy(false);
    setStatus("");
  }
}

async function logout() {
  if (model.busy) return;
  setError("");
  setStatus(t("loggingOut"));
  setBusy(true);
  try {
    await request("/api/account/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    announceAccountChange();
    model.account = null;
    model.legacyAvailable = false;
    render();
  } catch (error) {
    setError(t("requestFailed", { message: errorMessage(error) }));
  } finally {
    setBusy(false);
    setStatus("");
  }
}

async function importLegacy() {
  if (model.busy || !model.legacyAvailable) return;
  const expectedAccountId = model.account?.id;
  if (!expectedAccountId) return;
  if (!window.confirm(t("importLegacyConfirm"))) return;
  setError("");
  setStatus(t("importing"));
  setBusy(true);
  try {
    const session = await request("/api/account/session");
    if (accountFromPayload(session)?.id !== expectedAccountId) {
      model.account = accountFromPayload(session);
      model.legacyAvailable = session?.legacy_available === true;
      render();
      setStatus("");
      return;
    }
    await request("/api/account/import-legacy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: expectedAccountId }),
    });
    model.legacyAvailable = false;
    renderSession();
    setStatus(t("importLegacyDone"));
  } catch (error) {
    setError(t("importLegacyFailed", { message: errorMessage(error) }));
    setStatus("");
  } finally {
    setBusy(false);
  }
}

refs.form.addEventListener("submit", submitForm);
refs.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    if (model.busy || model.mode === tab.dataset.mode) return;
    model.mode = tab.dataset.mode === "register" ? "register" : "login";
    setError("");
    refs.form.reset();
    renderMode();
    refs.username.focus();
  });
});
refs.localeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (model.busy || !COPY[button.dataset.locale]) return;
    model.locale = button.dataset.locale;
    storeLocale(model.locale);
    render();
  });
});
refs.logout.addEventListener("click", () => { void logout(); });
refs.importLegacy.addEventListener("click", () => { void importLegacy(); });

render();
void loadSession().then((authenticatedWithRedirect) => {
  if (!authenticatedWithRedirect) render();
});

window.addEventListener("storage", (event) => {
  if (event.key === "fireplace.auth-change" && !model.busy) void loadSession();
});
window.addEventListener("focus", () => { if (!model.busy) void loadSession(); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !model.busy) void loadSession();
});
