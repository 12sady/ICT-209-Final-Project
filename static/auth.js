// Shared by the sign-up and log-in pages: a Show/Hide button beside each
// password field (hidden by default), and (on sign-up) a live checklist of
// the username format rules.

document.querySelectorAll(".pw-toggle").forEach((btn) => {
  const input = btn.parentElement.querySelector(".pw-field");
  btn.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    btn.setAttribute("aria-pressed", String(show));
    input.focus();
  });
});

const userInput = document.getElementById("username");
const ruleEls = document.querySelectorAll("[data-rule]");
if (userInput && ruleEls.length) {
  const rules = {
    length: (v) => v.length >= 3 && v.length <= 30,
    chars: (v) => v.length > 0 && /^[A-Za-z0-9._-]+$/.test(v),
    edges: (v) => /^[A-Za-z0-9]/.test(v) && /[A-Za-z0-9]$/.test(v),
  };
  const update = () => {
    const v = userInput.value;
    ruleEls.forEach((li) => {
      const ok = rules[li.dataset.rule](v);
      li.classList.toggle("rule-ok", ok);
      li.classList.toggle("rule-bad", !ok && v.length > 0);
    });
  };
  userInput.addEventListener("input", update);
  update();
}
