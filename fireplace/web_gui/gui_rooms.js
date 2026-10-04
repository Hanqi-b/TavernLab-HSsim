const API = {
  current: "/api/rooms/current",
  create: "/api/rooms/create",
  join: "/api/rooms/join",
  leave: "/api/rooms/leave",
};

const ROOM_MODE = "human_human";

/**
 * Room lobby and account-scoped invite handling.
 *
 * The room registry remains server authoritative.  This module only owns the
 * controls around its HTTP contract and the one piece of client persistence
 * that is useful for a creator: the invite code while the room is waiting.
 */
export function createRooms({
  window, document, elements, locale, dom, data,
  getAccount, getNickname, getDeckId, getSnapshot,
  onPayload, onSetLobbyStatus,
}) {
  let room = null;
  let roomBusy = false;
  let requestGeneration = 0;
  let initialized = false;

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function safeText(value, fallback = "") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function normalizeRoom(value) {
    if (!isObject(value)) return null;
    const status = ["waiting", "playing", "complete"].includes(String(value.status || "").toLowerCase())
      ? String(value.status).toLowerCase() : "waiting";
    const id = safeText(value.id || value.room_id || value.roomId, "").trim();
    if (!id) return null;
    const seat = value.seat === 0 || value.seat === 1 ? value.seat : null;
    const participants = Array.isArray(value.participants)
      ? value.participants.map((participant) => {
        if (!isObject(participant)) return null;
        const participantSeat = participant.seat === 0 || participant.seat === 1
          ? participant.seat : null;
        const nickname = safeText(participant.nickname || participant.name, "").trim();
        if (participantSeat === null || !nickname) return null;
        return { seat: participantSeat, nickname };
      }).filter(Boolean)
      : [];
    const inviteCode = safeText(value.invite_code || value.inviteCode, "").trim();
    return {
      id,
      status,
      seat,
      participants,
      invite_code: inviteCode || null,
      session_id: safeText(value.session_id, "") || null,
      revision: Number.isFinite(value.revision) ? value.revision : null,
    };
  }

  function roomFromPayload(payload) {
    if (!isObject(payload)) return null;
    if (isObject(payload.room)) return normalizeRoom(payload.room);
    if (isObject(payload.snapshot) && isObject(payload.snapshot.room)) {
      return normalizeRoom(payload.snapshot.room);
    }
    if (isObject(payload.state) && isObject(payload.state.room)) {
      return normalizeRoom(payload.state.room);
    }
    // /api/rooms/current may return the room DTO directly while the normal
    // state/action endpoints wrap it under ``room``.
    if (payload.id || payload.room_id || payload.roomId) return normalizeRoom(payload);
    return null;
  }

  function accountId() {
    const account = typeof getAccount === "function" ? getAccount() : null;
    return account && typeof account.id === "string" ? account.id.trim() : "anonymous";
  }

  function storageKey(roomId) {
    return `fireplace.roomInvite.${accountId()}.${safeText(roomId, "")}`;
  }

  function storedInvite(roomId) {
    if (!roomId) return "";
    return locale.readStored(storageKey(roomId), "").trim();
  }

  function rememberInvite(nextRoom) {
    if (!nextRoom || !nextRoom.id || !nextRoom.invite_code || nextRoom.status !== "waiting") return;
    locale.writeStored(storageKey(nextRoom.id), nextRoom.invite_code);
  }

  function clearInvite(nextRoom = room) {
    if (!nextRoom || !nextRoom.id) return;
    try { window.localStorage.removeItem(storageKey(nextRoom.id)); } catch (_error) { /* storage is optional */ }
  }

  function currentInvite(nextRoom) {
    if (!nextRoom || nextRoom.status !== "waiting") return "";
    return nextRoom.invite_code || storedInvite(nextRoom.id);
  }

  function setText(id, value) {
    dom.setText(elements[id], value || "");
  }

  function setHidden(id, hidden) {
    dom.setHidden(elements[id], hidden);
  }

  function setRoomStatus(message, kind = "") {
    setText("room-controls-status", message);
    if (elements["room-controls-status"]) {
      elements["room-controls-status"].className = `room-status-pill${kind ? ` ${kind}` : ""}`;
    }
  }

  function setLobbyStatus(message, kind) {
    if (typeof onSetLobbyStatus === "function") onSetLobbyStatus(message, kind);
  }

  function participantLabel(participant) {
    const seat = participant.seat + 1;
    const own = room && room.seat === participant.seat ? ` · ${locale.tr("room.you")}` : "";
    return locale.tr("room.seatParticipant", { seat, nickname: participant.nickname }) + own;
  }

  function renderParticipants(nextRoom) {
    const list = elements["room-participants"];
    if (!list) return;
    dom.clear(list);
    const participants = nextRoom && Array.isArray(nextRoom.participants)
      ? nextRoom.participants : [];
    participants.forEach((participant) => {
      const item = document.createElement("li");
      item.textContent = participantLabel(participant);
      list.appendChild(item);
    });
    if (!participants.length) {
      const item = document.createElement("li");
      item.textContent = locale.tr("room.noParticipants");
      list.appendChild(item);
    }
  }

  function renderInvite(nextRoom) {
    const invite = currentInvite(nextRoom);
    const inviteInput = elements["room-invite-code"];
    if (inviteInput) inviteInput.value = invite;
    setHidden("room-invite-row", !invite);
    if (invite && nextRoom && nextRoom.invite_code) rememberInvite(nextRoom);
  }

  function opponentName(nextRoom) {
    if (!nextRoom || nextRoom.seat === null) return "";
    const opponent = nextRoom.participants.find((participant) => participant.seat !== nextRoom.seat);
    return opponent ? opponent.nickname : "";
  }

  function renderMatchStatus(nextRoom) {
    const visible = Boolean(nextRoom && (nextRoom.status === "playing" || nextRoom.status === "complete"));
    setHidden("room-match-status", !visible);
    if (!visible) return;
    setText("room-match-label", locale.tr("room.matchLabel"));
    setText("room-match-seat", nextRoom.seat === null
      ? locale.tr("room.seatUnknown")
      : locale.tr("room.yourSeat", { seat: nextRoom.seat + 1 }));
    const opponent = opponentName(nextRoom);
    setText("room-match-opponent", opponent
      ? locale.tr("room.opponent", { nickname: opponent }) : locale.tr("room.opponentWaiting"));
    setText("room-match-state", nextRoom.status === "complete"
      ? locale.tr("room.complete") : locale.tr("room.playing"));
  }

  function renderControls(nextRoom = room) {
    const waiting = Boolean(nextRoom && nextRoom.status === "waiting");
    const hasRoom = Boolean(nextRoom);
    setHidden("room-setup-actions", hasRoom);
    setHidden("room-waiting-panel", !waiting);
    if (waiting) {
      setText("room-waiting-title", locale.tr("room.waitingTitle"));
      setText("room-waiting-message", locale.tr("room.waitingMessage"));
      setText("room-cancel-button", locale.tr("room.cancel"));
      setText("room-copy-button", locale.tr("room.copy"));
      setText("room-invite-label", locale.tr("room.inviteCode"));
      setText("room-invite-hint", locale.tr("room.copyHint"));
      setText("room-participants-label", locale.tr("room.participants"));
      renderInvite(nextRoom);
      renderParticipants(nextRoom);
      setRoomStatus(locale.tr("room.waitingStatus"));
    } else if (!hasRoom) {
      setRoomStatus("");
    } else {
      setRoomStatus(nextRoom.status === "complete" ? locale.tr("room.complete") : locale.tr("room.playing"));
    }
    renderMatchStatus(nextRoom);
  }

  function renderCopy() {
    setText("room-controls-title", locale.tr("room.title"));
    setText("room-controls-description", locale.tr("room.description"));
    setText("room-create-button", locale.tr("room.create"));
    setText("room-code-label", locale.tr("room.inviteCode"));
    setText("room-code-hint", locale.tr("room.joinHint"));
    setText("room-join-button", locale.tr("room.join"));
    setText("room-cancel-button", locale.tr("room.cancel"));
    setText("room-copy-button", locale.tr("room.copy"));
    setText("room-invite-label", locale.tr("room.inviteCode"));
    setText("room-invite-hint", locale.tr("room.copyHint"));
    setText("room-participants-label", locale.tr("room.participants"));
    setText("room-waiting-title", locale.tr("room.waitingTitle"));
    if (elements["room-code-input"]) elements["room-code-input"].setAttribute("aria-label", locale.tr("room.inviteCode"));
    if (elements["room-invite-code"]) elements["room-invite-code"].setAttribute("aria-label", locale.tr("room.inviteCode"));
  }

  function render(nextRoom = room) {
    renderCopy();
    renderControls(nextRoom);
  }

  function setMode(mode) {
    if (room && mode !== ROOM_MODE) {
      // A member must leave the current room through its explicit cancel or
      // terminal return action; switching the selector must not accidentally
      // try to start a separate personal match beside it.
      activateMode();
      return;
    }
    const enabled = mode === ROOM_MODE;
    setHidden("room-controls", !enabled);
    if (!enabled) {
      setHidden("room-waiting-panel", true);
      renderMatchStatus(room);
      return;
    }
    render(room);
  }

  function applyRoom(nextRoom) {
    const previous = room;
    room = nextRoom;
    if (previous && (!nextRoom || previous.id !== nextRoom.id || nextRoom.status !== "waiting")) {
      clearInvite(previous);
    }
    if (room && room.status === "waiting") rememberInvite(room);
    if (room && room.status !== "waiting") clearInvite(room);
    if (room) activateMode();
    render(room);
    return room;
  }

  function acceptPayload(payload) {
    const nextRoom = roomFromPayload(payload);
    applyRoom(nextRoom);
    if (typeof onPayload === "function" && isObject(payload) &&
        (payload.mode === "lobby" || payload.mode === "match" || payload.snapshot || payload.observation)) {
      return onPayload(payload);
    }
    return payload;
  }

  function parsePayload(response) {
    return response.text().then((body) => {
      let payload = {};
      if (body) {
        try { payload = JSON.parse(body); } catch (_error) { throw new Error(locale.tr("invalidJson", { value: response.status })); }
      }
      if (!response.ok) {
        const raw = payload && payload.error;
        const message = isObject(raw) ? raw.message : raw;
        const error = new Error(safeText(message, `HTTP ${response.status}`));
        error.payload = payload;
        error.status = response.status;
        throw error;
      }
      return payload;
    });
  }

  function request(path, options = {}) {
    return window.fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
    }).then(parsePayload);
  }

  function deckId() {
    const value = typeof getDeckId === "function" ? getDeckId() : "";
    return typeof value === "string" ? value.trim() : "";
  }

  function requestBody(extra = {}) {
    const body = {
      nickname: typeof getNickname === "function" ? getNickname() : "",
      locale: locale.locale,
      ...extra,
    };
    const selectedDeck = deckId();
    if (selectedDeck) body.deck_id = selectedDeck;
    return body;
  }

  function setControlsDisabled(disabled) {
    ["room-create-button", "room-join-button", "room-code-input", "room-cancel-button", "room-copy-button"]
      .forEach((id) => { if (elements[id]) elements[id].disabled = Boolean(disabled); });
  }

  function runRequest(path, body, message) {
    if (roomBusy) return Promise.resolve(null);
    const generation = ++requestGeneration;
    roomBusy = true;
    setControlsDisabled(true);
    setRoomStatus(message);
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((payload) => {
      if (generation !== requestGeneration) return null;
      acceptPayload(payload);
      return payload;
    }).catch((error) => {
      if (generation !== requestGeneration) return null;
      if (error && error.payload) {
        const errorRoom = roomFromPayload(error.payload);
        if (errorRoom) applyRoom(errorRoom);
      }
      const messageText = data.errorMessage(error);
      setRoomStatus(messageText, "error");
      setLobbyStatus(locale.tr("room.requestFailed", { message: messageText }), "error");
      return null;
    }).finally(() => {
      if (generation !== requestGeneration) return;
      roomBusy = false;
      setControlsDisabled(false);
      render(room);
    });
  }

  function create() {
    if (!isRoomMode() || roomBusy) return Promise.resolve(null);
    const nickname = typeof getNickname === "function" ? getNickname() : "";
    if (!nickname) {
      setRoomStatus(locale.tr("lobby.enterName"), "error");
      return Promise.resolve(null);
    }
    return runRequest(API.create, requestBody(), locale.tr("room.creating"));
  }

  function join() {
    if (!isRoomMode() || roomBusy) return Promise.resolve(null);
    const input = elements["room-code-input"];
    const code = input && typeof input.value === "string" ? input.value.trim() : "";
    if (!code) {
      setRoomStatus(locale.tr("room.enterCode"), "error");
      if (input) input.focus();
      return Promise.resolve(null);
    }
    const nickname = typeof getNickname === "function" ? getNickname() : "";
    if (!nickname) {
      setRoomStatus(locale.tr("lobby.enterName"), "error");
      return Promise.resolve(null);
    }
    // The authenticated room boundary calls the creator's one-time code
    // `invite_code`; keep the raw input local so it is never rendered back
    // through an HTML interpolation path.
    return runRequest(API.join, requestBody({ invite_code: code }), locale.tr("room.joining"));
  }

  function leave() {
    if (roomBusy || !room) return Promise.resolve(null);
    const snapshot = typeof getSnapshot === "function" ? getSnapshot() : null;
    const body = {
      room_id: room.id,
      session_id: snapshot?.session_id || room.session_id || "",
      revision: Number.isFinite(snapshot?.revision) ? snapshot.revision : room.revision,
    };
    const generation = ++requestGeneration;
    roomBusy = true;
    setControlsDisabled(true);
    setRoomStatus(locale.tr("room.leaving"));
    return request(API.leave, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((payload) => {
      if (generation !== requestGeneration) return null;
      const previous = room;
      clearInvite(previous);
      room = null;
      render(null);
      return acceptPayload(payload);
    }).catch((error) => {
      if (generation !== requestGeneration) return null;
      const message = data.errorMessage(error);
      setRoomStatus(message, "error");
      setLobbyStatus(locale.tr("room.leaveFailed", { message }), "error");
      return null;
    }).finally(() => {
      if (generation !== requestGeneration) return;
      roomBusy = false;
      setControlsDisabled(false);
      render(room);
    });
  }

  async function copyInvite() {
    const input = elements["room-invite-code"];
    const code = input && typeof input.value === "string" ? input.value.trim() : "";
    if (!code) return;
    let copied = false;
    try {
      if (window.navigator?.clipboard && typeof window.navigator.clipboard.writeText === "function") {
        await window.navigator.clipboard.writeText(code);
        copied = true;
      }
    } catch (_error) { /* fall back to a selectable field */ }
    if (!copied && input) {
      input.focus();
      input.select();
      try { copied = document.execCommand && document.execCommand("copy"); } catch (_error) { copied = false; }
    }
    setRoomStatus(copied ? locale.tr("room.copied") : locale.tr("room.copyManual"));
  }

  function renderPayload(payload) {
    const nextRoom = roomFromPayload(payload);
    applyRoom(nextRoom);
    return nextRoom;
  }

  async function loadCurrent() {
    try {
      const payload = await request(API.current);
      const nextRoom = roomFromPayload(payload);
      if (nextRoom) {
        applyRoom(nextRoom);
        if (nextRoom.status === "waiting") activateMode();
      } else {
        applyRoom(null);
      }
      return nextRoom;
    } catch (_error) {
      // /api/state remains the authoritative recovery path when an older
      // server does not expose rooms/current yet.
      return room;
    }
  }

  function activateMode() {
    const select = elements["battle-mode-select"];
    if (!select || select.value === ROOM_MODE) return;
    select.value = ROOM_MODE;
    select.dataset.userSelected = "true";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  }

  function isRoomMode() {
    return elements["battle-mode-select"]?.value === ROOM_MODE;
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    elements["room-create-button"]?.addEventListener("click", () => { void create(); });
    elements["room-join-button"]?.addEventListener("click", () => { void join(); });
    elements["room-code-input"]?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); void join(); }
    });
    elements["room-cancel-button"]?.addEventListener("click", () => { void leave(); });
    elements["room-copy-button"]?.addEventListener("click", () => { void copyInvite(); });
  }

  function init() {
    bind();
    render(room);
    return loadCurrent();
  }

  return {
    activateMode,
    create,
    init,
    isBusy: () => roomBusy,
    isRoomMode,
    join,
    leave,
    loadCurrent,
    render,
    renderPayload,
    setMode,
    get current() { return room; },
  };
}

export { ROOM_MODE };
