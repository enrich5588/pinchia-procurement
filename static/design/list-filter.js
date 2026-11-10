/* Client filter for rows already rendered on the page. Does not query the server. */
(() => {
  const closed = new Set(["已提供", "取消", "已核准", "已結案", "已撤回", "已完成"]);
  document.querySelectorAll("[data-list-filter]").forEach((root) => {
    const rows = [...root.querySelectorAll("[data-list-row]")];
    const query = root.querySelector("[data-list-query]");
    const dept = root.querySelector("[data-list-dept]");
    const statusSelect = root.querySelector("[data-list-status]");
    const empty = root.querySelector("[data-list-empty]");
    const tabs = [...root.querySelectorAll("[data-status-tab]")];
    let active = "";
    const apply = () => {
      const q = (query?.value || "").trim().toLowerCase();
      const department = dept?.value || "";
      const status = statusSelect?.value || active;
      let visible = 0;
      rows.forEach((row) => {
        const rowStatus = row.dataset.status || "";
        const statusOk = !status || (status === "closed" ? closed.has(rowStatus) : rowStatus === status);
        const deptOk = !department || row.dataset.dept === department;
        const textOk = !q || row.textContent.toLowerCase().includes(q);
        const show = statusOk && deptOk && textOk;
        if (!show) {
          row.querySelectorAll("input[type='checkbox']").forEach((box) => {
            if (!box.checked) return;
            box.checked = false;
            box.dispatchEvent(new Event("change", { bubbles: true }));
          });
        }
        row.hidden = !show;
        if (show) visible += 1;
      });
      if (empty) empty.hidden = visible !== 0 || rows.length === 0;
    };
    const resetTabs = (current) => {
      tabs.forEach((tab) => {
        const on = tab === current;
        tab.classList.toggle("active", on);
        tab.setAttribute("aria-pressed", String(on));
      });
    };
    query?.addEventListener("input", apply);
    dept?.addEventListener("change", apply);
    statusSelect?.addEventListener("change", () => {
      active = "";
      resetTabs(tabs[0]);
      apply();
    });
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      active = tab.dataset.statusTab || "";
      if (statusSelect) statusSelect.selectedIndex = 0;
      resetTabs(tab);
      apply();
    }));
    root.querySelector("[data-list-reset]")?.addEventListener("click", () => {
      if (query) query.value = "";
      if (dept) dept.selectedIndex = 0;
      if (statusSelect) statusSelect.selectedIndex = 0;
      active = "";
      resetTabs(tabs[0]);
      apply();
    });
  });
})();
