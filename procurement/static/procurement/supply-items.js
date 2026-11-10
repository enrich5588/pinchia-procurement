(() => {
  const bindOfficeSupplyItems = (root = document) => {
    const form = root.querySelector("[data-supply-form]");
    if (!form || form.dataset.itemsBound) return;
    form.dataset.itemsBound = "true";
    const list = form.querySelector("[data-supply-item-list]");
    const template = form.querySelector("[data-empty-supply-item]");
    const total = form.querySelector("[name='items-TOTAL_FORMS']");

    const updateCustomName = (row) => {
      const select = row.querySelector("select[name$='-product']");
      const field = row.querySelector("[data-custom-name-field]");
      const input = field?.querySelector("input");
      const isOther = select?.value === "other";
      if (field) field.hidden = !isOther;
      if (input) {
        if (!isOther) input.value = "";
        input.disabled = !isOther;
        input.required = isOther;
      }
    };
    const bindRow = (row) => {
      const select = row.querySelector("select[name$='-product']");
      select?.addEventListener("change", () => updateCustomName(row));
      row.querySelector("[data-remove-supply-item]")?.addEventListener("click", () => {
        const deleteInput = row.querySelector("input[name$='-DELETE']");
        if (deleteInput) deleteInput.checked = true;
        row.hidden = true;
      });
      updateCustomName(row);
    };
    list.querySelectorAll("[data-supply-item-row]").forEach(bindRow);
    form.querySelector("[data-add-supply-item]")?.addEventListener("click", () => {
      const index = Number(total.value);
      const wrapper = document.createElement("div");
      wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index)).trim();
      const row = wrapper.firstElementChild;
      list.appendChild(row);
      total.value = index + 1;
      bindRow(row);
      row.querySelector("select")?.focus();
    });
  };
  window.bindOfficeSupplyItems = bindOfficeSupplyItems;
  bindOfficeSupplyItems();
})();
