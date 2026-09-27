"use strict";

// Demo sign-in only. This does not protect the public API or replace server authentication.
const GridlockAuth = (() => {
  const SESSION_KEY = "gridlockCompany";
  const DEMO_PASSWORD = "gridlock123";
  const companies = Object.freeze([
    Object.freeze({ id: "GPC", name: "Georgia Power" }),
    Object.freeze({ id: "DESC", name: "Dominion Energy South Carolina" }),
  ]);

  function accountFor(username) {
    const normalized = String(username || "").trim().replace(/\s+/g, " ").toLowerCase();
    return companies.find((company) => company.name.toLowerCase() === normalized) || null;
  }

  function signIn(username, password) {
    const account = accountFor(username);
    if (!account || password !== DEMO_PASSWORD) return null;
    sessionStorage.setItem(SESSION_KEY, account.id);
    return account;
  }

  function current() {
    const id = sessionStorage.getItem(SESSION_KEY);
    return companies.find((company) => company.id === id) || null;
  }

  function signOut() {
    sessionStorage.removeItem(SESSION_KEY);
  }

  return Object.freeze({ companies, accountFor, signIn, current, signOut });
})();
