"use strict";

(() => {
  const account = GridlockAuth.current();
  if (!account) return;

  const CHAT_API = "http://localhost:8000";
  const NAME_KEY = `gridlockChatName:${account.id}`;
  const companyNames = { GPC: "Georgia Power", DESC: "Dominion Energy SC" };
  const kindNames = {
    job_update: "Job update",
    tool_request: "Tool request",
    equipment_request: "Equipment request",
  };
  const toggle = document.querySelector("#chat-toggle");
  const panel = document.querySelector("#chat-panel");
  const close = document.querySelector("#chat-close");
  const list = document.querySelector("#chat-messages");
  const status = document.querySelector("#chat-status");
  const unreadBadge = document.querySelector("#chat-unread");
  const form = document.querySelector("#chat-form");
  const nameInput = document.querySelector("#chat-name");
  const kindInput = document.querySelector("#chat-kind");
  const referenceInput = document.querySelector("#chat-reference");
  const bodyInput = document.querySelector("#chat-body");
  const sendButton = document.querySelector("#chat-send");

  let lastId = 0;
  let initialized = false;
  let loading = false;
  let unread = 0;
  const shownIds = new Set();
  nameInput.value = sessionStorage.getItem(NAME_KEY) || "";

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  }

  function setUnread(count) {
    unread = count;
    unreadBadge.hidden = count === 0;
    unreadBadge.textContent = count > 9 ? "9+" : String(count);
  }

  function showEmptyState() {
    if (list.children.length) return;
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.textContent = "No messages yet. Start the conversation with a job update or a request.";
    list.appendChild(empty);
  }

  function renderMessage(message) {
    const item = document.createElement("article");
    item.className = `chat-message${message.company === account.id ? " is-own-company" : ""}`;

    const heading = document.createElement("div");
    heading.className = "chat-message-heading";
    const sender = document.createElement("strong");
    sender.textContent = message.sender_name;
    const company = document.createElement("span");
    company.textContent = companyNames[message.company] || message.company;
    const time = document.createElement("time");
    const date = new Date(message.created_at);
    time.dateTime = message.created_at;
    time.textContent = Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    heading.append(sender, company, time);

    const type = document.createElement("div");
    type.className = `chat-message-type type-${message.kind}`;
    type.textContent = kindNames[message.kind] || "Message";
    if (message.reference) {
      const reference = document.createElement("span");
      reference.textContent = ` · ${message.reference}`;
      type.appendChild(reference);
    }

    const body = document.createElement("p");
    body.className = "chat-message-body";
    body.textContent = message.body;
    item.append(heading, type, body);
    return item;
  }

  function appendMessages(messages, initial = false) {
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    let added = 0;
    if (initial) {
      list.replaceChildren();
      shownIds.clear();
    }
    for (const message of messages) {
      if (shownIds.has(message.id)) continue;
      list.querySelector(".chat-empty")?.remove();
      list.appendChild(renderMessage(message));
      shownIds.add(message.id);
      lastId = Math.max(lastId, message.id);
      added += 1;
    }
    if (initial) showEmptyState();
    if (initial || nearBottom) list.scrollTop = list.scrollHeight;
    if (!initial && panel.hidden && added) setUnread(unread + added);
  }

  async function refreshMessages() {
    if (loading) return;
    loading = true;
    try {
      const initial = !initialized;
      const url = initial ? `${CHAT_API}/messages?limit=100` : `${CHAT_API}/messages?after_id=${lastId}&limit=200`;
      const response = await fetch(url);
      if (!response.ok) throw new Error("Could not load messages");
      appendMessages(await response.json(), initial);
      initialized = true;
      if (initial) sendButton.disabled = false;
      setStatus("");
    } catch {
      setStatus("Chat is unavailable. Check that the API server is running.", true);
    } finally {
      loading = false;
    }
  }

  function setOpen(open) {
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      setUnread(0);
      refreshMessages();
      (nameInput.value ? bodyInput : nameInput).focus();
    } else {
      toggle.focus();
    }
  }

  toggle.addEventListener("click", () => setOpen(panel.hidden));
  close.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) setOpen(false);
  });
  nameInput.addEventListener("change", () => {
    sessionStorage.setItem(NAME_KEY, nameInput.value.trim());
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!initialized) {
      setStatus("Waiting for chat to connect. Please try again shortly.", true);
      return;
    }
    const senderName = nameInput.value.trim();
    const body = bodyInput.value.trim();
    if (!senderName || !body) {
      setStatus("Enter your name and a message before sending.", true);
      return;
    }
    sessionStorage.setItem(NAME_KEY, senderName);
    sendButton.disabled = true;
    setStatus("Sending…");
    try {
      const response = await fetch(`${CHAT_API}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: account.id,
          sender_name: senderName,
          kind: kindInput.value,
          reference: referenceInput.value.trim(),
          body,
        }),
      });
      if (!response.ok) throw new Error("Could not send message");
      appendMessages([await response.json()]);
      bodyInput.value = "";
      list.scrollTop = list.scrollHeight;
      setStatus("Message sent.");
      bodyInput.focus();
    } catch {
      setStatus("Message was not sent. Check the API server and try again.", true);
    } finally {
      sendButton.disabled = false;
    }
  });

  refreshMessages();
  window.setInterval(refreshMessages, 5000);
})();
