/* Shell interactions only: mobile drawer, focus trap, and Escape to close. */
(() => {
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.querySelector(".drawer-backdrop");
  if (!sidebar) return;
  const buttons = () => [...document.querySelectorAll("[data-drawer]")];
  const setOpen = (open) => {
    sidebar.classList.toggle("open", open);
    backdrop?.classList.toggle("show", open);
    buttons().forEach((button) => button.setAttribute("aria-expanded", String(open)));
    document.body.style.overflow = open ? "hidden" : "";
    if (open) sidebar.querySelector("a, button")?.focus();
  };
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-drawer]")) {
      event.preventDefault();
      setOpen(!sidebar.classList.contains("open"));
      return;
    }
    if (event.target.closest("[data-close-drawer]")) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.classList.contains("open")) setOpen(false);
    if (event.key !== "Tab" || !sidebar.classList.contains("open")) return;
    const nodes = [...sidebar.querySelectorAll("a, button")];
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 760) setOpen(false);
  });
})();
