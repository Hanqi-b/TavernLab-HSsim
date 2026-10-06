const OFFICIAL_DOCS_URL = "https://learn.chatgpt.com/docs/codex/cli";
const OFFICIAL_LOGIN_URL = "https://auth.openai.com/";
const DEFAULT_POLL_INTERVAL = 2000;

const COPY = {
  zhCN: {
    eyebrow: "CODEX / LOCAL CLI",
    title: "连接本机 Codex",
    descriptionShared: "使用你自己安装的 Codex CLI 和已有 CLI 账号。点击“检查 CLI”读取本机 CLI 的登录状态；“登录本机 CLI 账号”会写入同一个 CLI 账号，“退出本机 CLI 账号”会使本机 CLI 退出登录。此页面不会下载或安装 CLI。",
    descriptionPrivate: "使用游戏专用的 Codex CLI 配置和账号额度。这里的登录只影响这个游戏的独立配置；退出不会退出其他 CLI。此页面不会下载或安装 CLI。",
    check: "检查 CLI",
    connectShared: "登录本机 CLI 账号",
    connectPrivate: "登录 Codex",
    cancel: "取消登录",
    logoutShared: "退出本机 CLI 账号",
    logoutPrivate: "退出游戏 Codex",
    test: "测试连接",
    advanced: "高级设置",
    advancedHint: "通常无需修改。代理只能填写未携带账号或令牌的 HTTP(S) 地址。",
    binaryLabel: "Codex CLI 路径",
    binaryPlaceholder: "留空：自动查找",
    binaryHint: "填写绝对路径；留空使用系统自动查找。",
    proxyLabel: "Codex 代理地址",
    proxyPlaceholder: "留空：继承环境设置",
    proxyHint: "只能使用 http:// 或 https://，且不能包含用户名或密码。",
    saveSettings: "保存高级设置",
    docs: "打开官方 Codex CLI 文档",
    continueLogin: "继续官方登录",
    loginFallback: "如果登录页没有自动打开，请继续使用官方登录页面：",
    missing: "请先自行安装 Codex CLI，然后返回这里重新检查。",
    availableShared: "Codex CLI 已安装。点击“检查 CLI”读取已有的本机 CLI 账号；如果尚未登录，再在终端运行 codex login。",
    availablePrivate: "Codex CLI 已安装，但独立配置尚未连接。",
    connected: "Codex 已连接，可以使用当前账号额度。",
    pending: "等待官方登录完成……完成后会自动更新状态。",
    unknown: "还没有读取 Codex 状态。",
    badgeConnected: "已连接",
    badgePending: "等待登录",
    badgeAvailable: "已安装",
    badgeMissing: "未安装",
    badgeUnknown: "未检查",
    missingTitle: "未找到 Codex CLI",
    accountPlan: "方案：{value}",
    accountUnknown: "已登录账号",
    checking: "正在检查 Codex 状态……",
    checkingShort: "检查中……",
    loggingInShared: "正在准备本机 CLI 账号登录……",
    loggingInPrivate: "正在准备官方登录……",
    cancelling: "正在取消登录……",
    loggingOutShared: "正在退出本机 CLI 账号……",
    loggingOutPrivate: "正在退出游戏 Codex……",
    testing: "正在测试连接……",
    saving: "正在保存高级设置……",
    checked: "Codex 状态已更新。",
    loginStarted: "已打开官方登录页面；完成登录后返回此页。",
    loginCancelled: "已取消登录请求。",
    loggedOutShared: "本机 CLI 账号已退出登录。",
    loggedOutPrivate: "游戏 Codex 已退出。",
    testPassed: "Codex 连接测试成功。",
    testFailed: "Codex 连接测试未通过，请检查模型、登录和代理设置后重试。",
    settingsSaved: "高级设置已保存。",
    networkError: "无法连接本机服务。请检查服务是否仍在运行，然后重试。",
    proxyError: "代理设置无法使用。请检查地址，或清空代理后重试。",
    notAuthenticatedShared: "本机 CLI 账号尚未登录或登录已过期。请先在终端运行 codex login，再点击“检查 CLI”。",
    notAuthenticatedPrivate: "独立 Codex 配置尚未登录或登录已过期。请点击“登录 Codex”。",
    missingExecutable: "未找到 Codex CLI。请从官方文档自行安装后，再点击“检查 CLI”。",
    genericError: "Codex 状态需要处理。请检查 CLI 后重试。",
    invalidBinary: "CLI 路径必须是绝对路径，或留空使用自动查找。",
    invalidProxy: "代理必须是未携带账号或密码的 http:// 或 https:// 地址，或留空。",
    unavailableTestShared: "请先在终端运行 codex login，再点击“检查 CLI”，然后测试连接。",
    unavailableTestPrivate: "请先安装并登录 Codex，再测试连接。",
  },
  enUS: {
    eyebrow: "CODEX / LOCAL CLI",
    title: "Connect local Codex",
    descriptionShared: "Use your installed Codex CLI and its existing account. Click “Check CLI” to read the local CLI login; “Log in to local CLI account” writes to that same account, and “Log out local CLI account” logs the local CLI out. This page never downloads or installs the CLI.",
    descriptionPrivate: "Use a separate Codex profile and account for this game. Login affects only that isolated profile; logging out does not affect another CLI profile. This page never downloads or installs the CLI.",
    check: "Check CLI",
    connectShared: "Log in to local CLI account",
    connectPrivate: "Log in to Codex",
    cancel: "Cancel login",
    logoutShared: "Log out local CLI account",
    logoutPrivate: "Log out game Codex",
    test: "Test connection",
    advanced: "Advanced settings",
    advancedHint: "Usually no changes are needed. Proxy URLs must be unauthenticated HTTP(S) addresses.",
    binaryLabel: "Codex CLI path",
    binaryPlaceholder: "Blank: auto-detect",
    binaryHint: "Use an absolute path, or leave blank for system discovery.",
    proxyLabel: "Codex proxy URL",
    proxyPlaceholder: "Blank: inherit environment",
    proxyHint: "Use http:// or https:// without a username or password.",
    saveSettings: "Save advanced settings",
    docs: "Open official Codex CLI docs",
    continueLogin: "Continue with official login",
    loginFallback: "If the login page did not open, continue with the official login page:",
    missing: "Install Codex CLI yourself, then return here and check again.",
    availableShared: "Codex CLI is installed. Click “Check CLI” to read the existing local CLI account; if no account is found, run codex login in a terminal.",
    availablePrivate: "Codex CLI is installed but the isolated profile is not connected.",
    connected: "Codex is connected and can use the current account allowance.",
    pending: "Waiting for official login to finish… The status will update automatically.",
    unknown: "Codex status has not been checked yet.",
    badgeConnected: "Connected",
    badgePending: "Login pending",
    badgeAvailable: "Installed",
    badgeMissing: "Not installed",
    badgeUnknown: "Not checked",
    missingTitle: "Codex CLI was not found",
    accountPlan: "Plan: {value}",
    accountUnknown: "Signed-in account",
    checking: "Checking Codex status…",
    checkingShort: "Checking…",
    loggingInShared: "Preparing local CLI account login…",
    loggingInPrivate: "Preparing official login…",
    cancelling: "Cancelling login…",
    loggingOutShared: "Logging out the local CLI account…",
    loggingOutPrivate: "Logging out of game Codex…",
    testing: "Testing the connection…",
    saving: "Saving advanced settings…",
    checked: "Codex status updated.",
    loginStarted: "The official login page is open. Finish login, then return here.",
    loginCancelled: "The login request was cancelled.",
    loggedOutShared: "The local CLI account is logged out.",
    loggedOutPrivate: "Game Codex is logged out.",
    testPassed: "Codex connection test succeeded.",
    testFailed: "Codex connection test did not pass. Check the model, login, and proxy settings, then retry.",
    settingsSaved: "Advanced settings saved.",
    networkError: "Could not reach the local service. Check that it is still running, then retry.",
    proxyError: "The proxy settings could not be used. Check the URL, or clear the proxy and retry.",
    notAuthenticatedShared: "The local CLI account is not signed in or the login has expired. Run codex login in a terminal, then click “Check CLI”.",
    notAuthenticatedPrivate: "The isolated Codex profile is not signed in or the login has expired. Click “Log in to Codex”.",
    missingExecutable: "Codex CLI was not found. Install it from the official docs, then click “Check CLI”.",
    genericError: "Codex status needs attention. Check the CLI and try again.",
    invalidBinary: "The CLI path must be absolute, or blank for automatic discovery.",
    invalidProxy: "The proxy must be an unauthenticated http:// or https:// URL, or blank.",
    unavailableTestShared: "Run codex login in a terminal, click “Check CLI”, then test the connection.",
    unavailableTestPrivate: "Install and log in to Codex before testing the connection.",
  },
};

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function interpolate(value, variables = {}) {
  return String(value).replace(/\{([a-zA-Z0-9_]+)\}/g, (_match, key) => (
    variables[key] === undefined ? `{${key}}` : String(variables[key])
  ));
}

function validText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeLocale(document, storageSource = globalThis) {
  let stored = "";
  try {
    stored = storageSource?.localStorage?.getItem("fireplace.locale") || "";
  } catch (_error) {
    // Storage can be unavailable in private browsing.
  }
  if (stored === "enUS") return "enUS";
  return document?.documentElement?.lang?.toLowerCase().startsWith("en") ? "enUS" : "zhCN";
}

function allowedAuthUrl(value) {
  const candidate = validText(value);
  if (!candidate) return null;
  try {
    const parsed = new URL(candidate);
    const host = parsed.hostname.toLowerCase();
    const officialHost = host === "auth.openai.com" || host === "chatgpt.com" || host.endsWith(".chatgpt.com");
    if (parsed.protocol !== "https:" || !officialHost) return null;
    return parsed.href;
  } catch (_error) {
    return null;
  }
}

function validProxyUrl(value) {
  const candidate = validText(value);
  if (!candidate) return "";
  try {
    const parsed = new URL(candidate);
    if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) return null;
    return candidate;
  } catch (_error) {
    return null;
  }
}

function isAbsolutePath(value) {
  return /^\/(?:[^/]|$)/.test(value) || /^[A-Za-z]:[\\/]/.test(value);
}

function friendlyErrorKind(value) {
  const text = validText(value).toLowerCase();
  if (!text) return "generic";
  if (/(not found|not installed|executable|binary|enoent|no such file|command not found)/.test(text)) return "missing";
  if (/(no account found|account not found|no account|not authenticated|unauthenticated|authentication|login required|logged out|token expired|expired|unauthorized|401)/.test(text)) return "auth";
  if (/(connection test failed|selected model)/.test(text)) return "test_failure";
  if (/(proxy|http proxy|https proxy)/.test(text)) return "proxy";
  if (/(network|connection|connect|timeout|timed out|unreachable|offline|fetch)/.test(text)) return "network";
  return "generic";
}

function safeDiagnostic(value) {
  const text = validText(value);
  if (!text || text.length > 240 || /(?:no account found|account not found|no account)/i.test(text) || /(token|secret|stderr|traceback|exception|private|authorization|bearer)/i.test(text)) {
    return "";
  }
  return /(codex|account|connection|settings|proxy|network|login|cli|model|openai|install|binary)/i.test(text)
    ? text : "";
}

function createNoopPanel() {
  return { destroy() {}, refresh() {} };
}

export function createCodexConnectionPanel({
  document = globalThis.document,
  window = globalThis.window,
  fetchImpl,
  pollInterval = DEFAULT_POLL_INTERVAL,
} = {}) {
  if (!document || !window) return createNoopPanel();

  const ids = [
    "codex-connection-panel", "codex-connection-eyebrow", "codex-connection-title",
    "codex-connection-description", "codex-connection-status", "codex-connection-error",
    "codex-connection-badge", "codex-connection-account", "codex-connection-account-email",
    "codex-connection-account-plan", "codex-connection-missing", "codex-connection-missing-copy",
    "codex-connection-docs-link", "codex-connection-login", "codex-connection-login-copy",
    "codex-connection-login-link", "codex-check-button", "codex-connect-button",
    "codex-cancel-button", "codex-logout-button", "codex-test-button", "codex-settings-button",
    "codex-connection-advanced-label", "codex-connection-advanced-hint", "codex-binary-path",
    "codex-binary-path-label", "codex-binary-path-hint", "codex-proxy-url", "codex-proxy-url-label",
    "codex-proxy-url-hint", "codex-connection-advanced", "lobby-form", "lobby-screen", "lobby-setup", "battle-mode-select",
    "opponent-select", "locale-zhCN", "locale-enUS", "codex-model-input", "codex-self-model-input",
    "codex-opponent-model-input",
  ];
  const refs = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
  if (!refs["codex-connection-panel"] || !refs["lobby-setup"] || !refs["battle-mode-select"] || !refs["opponent-select"]) {
    return createNoopPanel();
  }

  const requestFetch = fetchImpl || (typeof window.fetch === "function" ? window.fetch.bind(window) : null);
  let locale = normalizeLocale(document, window);
  let state = null;
  let visible = false;
  let statusLoaded = false;
  let statusInFlight = false;
  let statusEpoch = 0;
  let statusRequestSeq = 0;
  let actionInFlight = false;
  let pollingTimer = null;
  let observer = null;
  let destroyed = false;
  let lastErrorKind = "";
  let errorAnnouncement = "";
  let announcement = "";
  let loginUrl = null;
  let loginWindow = null;
  const dirtyFields = { binary: false, proxy: false };

  function copy(key, variables) {
    return interpolate(COPY[locale][key] || COPY.zhCN[key] || key, variables);
  }

  function usesSharedLogin() {
    return state?.shared_login !== false;
  }

  function modeCopy(sharedKey, privateKey, variables) {
    return copy(usesSharedLogin() ? sharedKey : privateKey, variables);
  }

  function isVisible() {
    const mode = validText(refs["battle-mode-select"].value);
    const opponent = validText(refs["opponent-select"].value);
    return !refs["lobby-screen"]?.hidden && !refs["lobby-setup"].hidden && (
      mode === "codex_codex" || mode === "codex_mcts" || (mode === "human" && opponent === "codex")
    );
  }

  function setText(node, value) {
    if (node) node.textContent = value;
  }

  function setHidden(node, hidden) {
    if (node) node.hidden = Boolean(hidden);
  }

  function setLink(node, href, label) {
    if (!node) return;
    node.href = href;
    node.textContent = label;
  }

  function renderCopy() {
    locale = normalizeLocale(document, window);
    setText(refs["codex-connection-eyebrow"], copy("eyebrow"));
    setText(refs["codex-connection-title"], copy("title"));
    setText(refs["codex-connection-description"], modeCopy("descriptionShared", "descriptionPrivate"));
    setText(refs["codex-check-button"], copy("check"));
    setText(refs["codex-connect-button"], modeCopy("connectShared", "connectPrivate"));
    setText(refs["codex-cancel-button"], copy("cancel"));
    setText(refs["codex-logout-button"], modeCopy("logoutShared", "logoutPrivate"));
    setText(refs["codex-test-button"], copy("test"));
    setText(refs["codex-connection-advanced-label"], copy("advanced"));
    setText(refs["codex-connection-advanced-hint"], copy("advancedHint"));
    setText(refs["codex-binary-path-label"], copy("binaryLabel"));
    setText(refs["codex-binary-path-hint"], copy("binaryHint"));
    setText(refs["codex-proxy-url-label"], copy("proxyLabel"));
    setText(refs["codex-proxy-url-hint"], copy("proxyHint"));
    setText(refs["codex-settings-button"], copy("saveSettings"));
    setText(refs["codex-connection-missing-copy"], copy("missing"));
    setText(refs["codex-connection-login-copy"], copy("loginFallback"));
    setLink(refs["codex-connection-docs-link"], OFFICIAL_DOCS_URL, copy("docs"));
    setLink(refs["codex-connection-login-link"], loginUrl || OFFICIAL_LOGIN_URL, copy("continueLogin"));
    if (refs["codex-binary-path"]) refs["codex-binary-path"].placeholder = copy("binaryPlaceholder");
    if (refs["codex-proxy-url"]) refs["codex-proxy-url"].placeholder = copy("proxyPlaceholder");
    if (refs["codex-binary-path"]) refs["codex-binary-path"].setAttribute("aria-label", copy("binaryLabel"));
    if (refs["codex-proxy-url"]) refs["codex-proxy-url"].setAttribute("aria-label", copy("proxyLabel"));
  }

  function sanitizeState(payload) {
    const source = isObject(payload?.status) ? payload.status : payload;
    if (!isObject(source)) return null;
    const accountSource = isObject(source.account) ? source.account : null;
    return {
      available: source.available === true,
      connected: source.connected === true,
      login_pending: source.login_pending === true,
      shared_login: source.shared_login !== false,
      error: validText(source.error),
      account: accountSource && validText(accountSource.email)
        ? { email: validText(accountSource.email), plan_type: validText(accountSource.plan_type) }
        : null,
      proxy_url: validText(source.proxy_url),
      binary_path: Object.prototype.hasOwnProperty.call(source, "binary_setting")
        ? validText(source.binary_setting) : validText(source.binary_path),
    };
  }

  function stateKind() {
    if (!state) return "unknown";
    if (state.login_pending) return "pending";
    if (state.connected) return "connected";
    if (state.available === false) return "missing";
    if (state.error) {
      const kind = friendlyErrorKind(state.error);
      if (kind === "missing") return "missing";
      if (kind === "auth") return "auth";
      if (kind === "proxy") return "proxy";
      if (kind === "network") return "network";
      return "error";
    }
    return state.available ? "available" : "missing";
  }

  function errorCopy(kind) {
    if (kind === "missing") return copy("missingExecutable");
    if (kind === "auth") return modeCopy("notAuthenticatedShared", "notAuthenticatedPrivate");
    if (kind === "test_failure") return copy("testFailed");
    if (kind === "proxy") return copy("proxyError");
    if (kind === "network") return copy("networkError");
    return copy("genericError");
  }

  function stateCopy(kind) {
    if (kind === "pending") return copy("pending");
    if (kind === "connected") return copy("connected");
    if (kind === "available") return modeCopy("availableShared", "availablePrivate");
    if (kind === "missing") return copy("missingTitle");
    if (kind === "auth" || kind === "network" || kind === "error") return copy("genericError");
    return copy("unknown");
  }

  function badgeCopy(kind) {
    if (kind === "connected") return copy("badgeConnected");
    if (kind === "pending") return copy("badgePending");
    if (kind === "available") return copy("badgeAvailable");
    if (kind === "missing") return copy("badgeMissing");
    return copy("badgeUnknown");
  }

  function updateFields() {
    if (!state) return;
    if (refs["codex-binary-path"] && !dirtyFields.binary) refs["codex-binary-path"].value = state.binary_path;
    if (refs["codex-proxy-url"] && !dirtyFields.proxy) refs["codex-proxy-url"].value = state.proxy_url;
  }

  function setActionAvailability(kind) {
    const connected = kind === "connected";
    const pending = kind === "pending";
    const missing = kind === "missing";
    setHidden(refs["codex-cancel-button"], !pending);
    setHidden(refs["codex-logout-button"], !connected);
    refs["codex-connect-button"].hidden = connected || pending;
    refs["codex-connect-button"].disabled = missing;
    refs["codex-test-button"].disabled = !connected;
    refs["codex-check-button"].disabled = false;
    if (actionInFlight) {
      ["codex-check-button", "codex-connect-button", "codex-cancel-button", "codex-logout-button", "codex-test-button", "codex-settings-button"]
        .forEach((id) => { if (refs[id]) refs[id].disabled = true; });
    }
  }

  function render() {
    renderCopy();
    const kind = stateKind();
    const panel = refs["codex-connection-panel"];
    panel.dataset.state = kind;
    setText(refs["codex-connection-status"], announcement || stateCopy(kind));
    setText(refs["codex-connection-badge"], badgeCopy(kind));
    setHidden(refs["codex-connection-missing"], kind !== "missing");
    setHidden(refs["codex-connection-account"], !state?.account);
    if (state?.account) {
      setText(refs["codex-connection-account-email"], state.account.email);
      setText(refs["codex-connection-account-plan"], state.account.plan_type
        ? copy("accountPlan", { value: state.account.plan_type }) : copy("accountUnknown"));
    }
    const errorKind = lastErrorKind || ((state?.error && kind !== "missing") ? friendlyErrorKind(state.error) : "");
    const diagnostic = kind === "missing" || errorKind === "test_failure" ? "" : safeDiagnostic(state?.error);
    setText(refs["codex-connection-error"], errorAnnouncement || diagnostic || (errorKind ? errorCopy(errorKind) : ""));
    setHidden(refs["codex-connection-error"], !errorAnnouncement && !diagnostic && !errorKind);
    setHidden(refs["codex-connection-login"], !loginUrl && !state?.login_pending);
    setLink(refs["codex-connection-login-link"], loginUrl || OFFICIAL_LOGIN_URL, copy("continueLogin"));
    setActionAvailability(kind);
    updateFields();
  }

  function stopPolling() {
    if (pollingTimer !== null) {
      window.clearInterval(pollingTimer);
      pollingTimer = null;
    }
  }

  function startPollingIfNeeded() {
    stopPolling();
    if (!visible || !state?.login_pending || destroyed) return;
    pollingTimer = window.setInterval(() => { void readStatus({ passive: true }); }, pollInterval);
  }

  function invalidateStatusReads() {
    statusEpoch += 1;
    statusRequestSeq += 1;
    statusInFlight = false;
    stopPolling();
  }

  function clearAnnouncement() {
    announcement = "";
  }

  function applyState(payload) {
    const next = sanitizeState(payload);
    if (!next) return false;
    state = next;
    statusLoaded = true;
    lastErrorKind = "";
    errorAnnouncement = "";
    if (state.connected) loginUrl = null;
    render();
    return true;
  }

  async function request(path, method = "GET", body) {
    if (!requestFetch) throw new Error("network");
    const options = {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    };
    if (method !== "GET") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body || {});
    }
    let response;
    try {
      response = await requestFetch(path, options);
    } catch (_error) {
      throw new Error("network");
    }
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* empty response */ }
    if (!response.ok) {
      const error = new Error(validText(payload?.error) || validText(payload?.message) || String(response.status));
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async function readStatus({ passive = false } = {}) {
    if (!visible || statusInFlight || actionInFlight || destroyed) return;
    const requestEpoch = statusEpoch;
    const requestSeq = ++statusRequestSeq;
    const isCurrentRequest = () => (
      visible && !destroyed && requestEpoch === statusEpoch && requestSeq === statusRequestSeq
    );
    statusInFlight = true;
    if (!passive && !state) {
      announcement = copy("checking");
      render();
    }
    try {
      const payload = await request("/api/codex/status");
      if (!isCurrentRequest()) return;
      statusLoaded = true;
      clearAnnouncement();
      if (!applyState(payload)) throw new Error("generic");
    } catch (error) {
      if (!isCurrentRequest()) return;
      statusLoaded = true;
      lastErrorKind = friendlyErrorKind(error.message);
      announcement = "";
      render();
    } finally {
      if (isCurrentRequest()) {
        statusInFlight = false;
        if (visible) startPollingIfNeeded();
      }
    }
  }

  function setBusy(action, busy) {
    actionInFlight = busy;
    refs["codex-connection-panel"].setAttribute("aria-busy", busy ? "true" : "false");
    refs["codex-connection-panel"].dataset.busy = busy ? action : "";
    ["codex-check-button", "codex-connect-button", "codex-cancel-button", "codex-logout-button", "codex-test-button", "codex-settings-button"]
      .forEach((id) => {
        if (!refs[id]) return;
        refs[id].disabled = busy;
        refs[id].setAttribute("aria-busy", busy ? "true" : "false");
      });
  }

  async function runAction(action, callback) {
    if (!visible || actionInFlight || destroyed) return;
    invalidateStatusReads();
    clearAnnouncement();
    lastErrorKind = "";
    errorAnnouncement = "";
    setBusy(action, true);
    const textKey = action === "check" ? "checkingShort"
      : action === "login" ? (usesSharedLogin() ? "loggingInShared" : "loggingInPrivate")
        : action === "cancel" ? "cancelling"
          : action === "logout" ? (usesSharedLogin() ? "loggingOutShared" : "loggingOutPrivate")
            : action === "test" ? "testing" : "saving";
    announcement = copy(textKey);
    render();
    try {
      const payload = await callback();
      if (payload && applyState(payload)) return payload;
      render();
      return payload;
    } catch (error) {
      lastErrorKind = friendlyErrorKind(error.message);
      errorAnnouncement = "";
      clearAnnouncement();
      render();
      return null;
    } finally {
      setBusy(action, false);
      render();
      if (visible && !destroyed) startPollingIfNeeded();
    }
  }

  function selectedModel() {
    const mode = validText(refs["battle-mode-select"].value);
    const opponent = validText(refs["opponent-select"].value);
    const candidates = mode === "human" && opponent === "codex"
      ? [refs["codex-model-input"]]
      : mode === "codex_codex"
        ? [refs["codex-self-model-input"], refs["codex-opponent-model-input"]]
        : [refs["codex-self-model-input"]];
    return candidates.map((node) => validText(node?.value)).find(Boolean) || "";
  }

  function openLoginWindow() {
    loginWindow = null;
    try {
      loginWindow = window.open("about:blank", "_blank");
      if (loginWindow) loginWindow.opener = null;
    } catch (_error) {
      loginWindow = null;
    }
  }

  function showLoginFallback(authUrl) {
    loginUrl = allowedAuthUrl(authUrl) || OFFICIAL_LOGIN_URL;
    setLink(refs["codex-connection-login-link"], loginUrl, copy("continueLogin"));
    setHidden(refs["codex-connection-login"], false);
    if (loginWindow && allowedAuthUrl(authUrl)) {
      try { loginWindow.location.href = loginUrl; } catch (_error) { /* fallback link remains */ }
    }
  }

  async function check() {
    await runAction("check", async () => {
      const payload = await request("/api/codex/check", "POST", {});
      announcement = copy("checked");
      return payload;
    });
  }

  async function login() {
    if (!visible || actionInFlight) return;
    openLoginWindow();
    await runAction("login", async () => {
      const payload = await request("/api/codex/login", "POST", {});
      showLoginFallback(payload?.auth_url);
      announcement = copy("loginStarted");
      return payload;
    });
  }

  async function cancelLogin() {
    await runAction("cancel", async () => {
      const payload = await request("/api/codex/cancel", "POST", {});
      loginUrl = null;
      announcement = copy("loginCancelled");
      return payload;
    });
  }

  async function logout() {
    await runAction("logout", async () => {
      const payload = await request("/api/codex/logout", "POST", {});
      loginUrl = null;
      announcement = modeCopy("loggedOutShared", "loggedOutPrivate");
      return payload;
    });
  }

  async function testConnection() {
    if (!state?.connected) {
      lastErrorKind = "auth";
      announcement = modeCopy("unavailableTestShared", "unavailableTestPrivate");
      errorAnnouncement = announcement;
      render();
      return;
    }
    await runAction("test", async () => {
      const model = selectedModel();
      const payload = await request("/api/codex/test", "POST", model ? { model } : {});
      announcement = payload?.success === true ? copy("testPassed") : copy("testFailed");
      return payload;
    });
  }

  async function saveSettings() {
    const binaryPath = validText(refs["codex-binary-path"]?.value);
    const proxyUrl = validProxyUrl(refs["codex-proxy-url"]?.value);
    if (binaryPath && !isAbsolutePath(binaryPath)) {
      lastErrorKind = "generic";
      announcement = copy("invalidBinary");
      errorAnnouncement = announcement;
      render();
      return;
    }
    if (proxyUrl === null) {
      lastErrorKind = "generic";
      announcement = copy("invalidProxy");
      errorAnnouncement = announcement;
      render();
      return;
    }
    await runAction("settings", async () => {
      const payload = await request("/api/codex/settings", "POST", {
        binary_path: binaryPath,
        proxy_url: proxyUrl,
      });
      dirtyFields.binary = false;
      dirtyFields.proxy = false;
      announcement = copy("settingsSaved");
      return payload;
    });
  }

  function syncVisibility() {
    if (destroyed) return;
    const nextVisible = isVisible();
    refs["codex-connection-panel"].hidden = !nextVisible;
    if (!nextVisible) {
      if (visible) {
        visible = false;
        statusLoaded = false;
      }
      invalidateStatusReads();
      return;
    }
    if (!visible) {
      visible = true;
      statusLoaded = false;
      void readStatus();
    } else if (!statusLoaded) {
      void readStatus();
    }
  }

  function bind() {
    renderCopy();
    refs["battle-mode-select"].addEventListener("change", syncVisibility);
    refs["opponent-select"].addEventListener("change", syncVisibility);
    refs["lobby-form"]?.addEventListener("submit", () => {
      window.setTimeout(syncVisibility, 0);
    });
    [refs["locale-zhCN"], refs["locale-enUS"]].forEach((button) => {
      button?.addEventListener("click", () => {
        window.setTimeout(() => { renderCopy(); render(); }, 0);
      });
    });
    refs["codex-check-button"].addEventListener("click", () => { void check(); });
    refs["codex-connect-button"].addEventListener("click", () => { void login(); });
    refs["codex-cancel-button"].addEventListener("click", () => { void cancelLogin(); });
    refs["codex-logout-button"].addEventListener("click", () => { void logout(); });
    refs["codex-test-button"].addEventListener("click", () => { void testConnection(); });
    refs["codex-settings-button"].addEventListener("click", () => { void saveSettings(); });
    refs["codex-binary-path"]?.addEventListener("input", () => { dirtyFields.binary = true; });
    refs["codex-proxy-url"]?.addEventListener("input", () => { dirtyFields.proxy = true; });
    if (typeof window.MutationObserver === "function") {
      observer = new window.MutationObserver(() => {
      const nextLocale = normalizeLocale(document, window);
        if (nextLocale !== locale) renderCopy();
        syncVisibility();
      });
      if (refs["lobby-screen"]) {
        observer.observe(refs["lobby-screen"], { attributes: true, attributeFilter: ["hidden", "class", "style"] });
      }
      observer.observe(refs["lobby-setup"], { attributes: true, attributeFilter: ["hidden", "class", "style"] });
      if (document.documentElement) observer.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    }
    syncVisibility();
  }

  function destroy() {
    destroyed = true;
    invalidateStatusReads();
    if (observer) observer.disconnect();
  }

  bind();
  return { destroy, refresh: syncVisibility };
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  const initialize = () => {
    if (!window.fireplaceCodexConnection) {
      window.fireplaceCodexConnection = createCodexConnectionPanel({ document, window });
    }
  };
  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
}
