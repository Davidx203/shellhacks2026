"use strict";

if (GridlockAuth.current()) {
  window.location.replace("./map.html");
} else {
  const form = document.querySelector("#login-form");
  const username = document.querySelector("#username");
  const password = document.querySelector("#password");
  const error = document.querySelector("#login-error");
  const options = [...document.querySelectorAll(".account-option")];

  function selectCompany(companyName) {
    username.value = companyName;
    options.forEach((option) => {
      option.setAttribute("aria-pressed", String(option.dataset.company === companyName));
    });
    error.hidden = true;
    password.focus();
  }

  options.forEach((option) => {
    option.addEventListener("click", () => selectCompany(option.dataset.company));
  });

  username.addEventListener("input", () => {
    const account = GridlockAuth.accountFor(username.value);
    options.forEach((option) => {
      option.setAttribute("aria-pressed", String(option.dataset.company === account?.name));
    });
    error.hidden = true;
  });

  document.querySelector("#toggle-password").addEventListener("click", (event) => {
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    event.currentTarget.textContent = visible ? "Show" : "Hide";
    event.currentTarget.setAttribute("aria-label", visible ? "Show password" : "Hide password");
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const account = GridlockAuth.signIn(username.value, password.value);
    if (!account) {
      error.textContent = "Use one of the two company names and the demo password.";
      error.hidden = false;
      password.select();
      return;
    }
    window.location.assign("./map.html");
  });
}
