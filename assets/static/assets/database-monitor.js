(() => {
  const root = document.querySelector("[data-database-monitor]");
  if (!root) return;
  const search = root.querySelector("[data-table-search]");
  const rows = [...root.querySelectorAll("[data-table-row]")];
  const empty = root.querySelector("[data-table-empty]");
  const select = root.querySelector("[data-refresh-select]");
  let timer;

  const schedule = (seconds) => {
    window.clearTimeout(timer);
    if (seconds > 0) timer = window.setTimeout(() => window.location.reload(), seconds * 1000);
  };
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      row.hidden = !row.dataset.tableName.includes(query);
      if (!row.hidden) visible += 1;
    });
    empty.hidden = visible !== 0;
  });
  select.addEventListener("change", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("refresh", select.value);
    window.location.assign(url);
  });
  root.querySelector("[data-refresh-now]").addEventListener("click", () => window.location.reload());
  schedule(Number(root.dataset.refreshSeconds));
})();
