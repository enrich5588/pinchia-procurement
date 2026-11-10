(() => {
  const bindEquipmentItems = (root = document) => {
    const form = root.querySelector("[data-equipment-form]");
    if (!form || form.dataset.itemsBound) return;
    form.dataset.itemsBound = "true";
    const list = form.querySelector("[data-equipment-item-list]");
    const template = form.querySelector("[data-empty-equipment-item]");
    const total = form.querySelector("[name='items-TOTAL_FORMS']");
    const bindRow = (row) => row.querySelector("[data-remove-equipment-item]")?.addEventListener("click", () => {
      const deleteInput = row.querySelector("input[name$='-DELETE']");
      if (deleteInput) deleteInput.checked = true;
      row.hidden = true;
    });
    list.querySelectorAll("[data-equipment-item-row]").forEach(bindRow);
    form.querySelector("[data-add-equipment-item]")?.addEventListener("click", () => {
      const index = Number(total.value);
      const wrapper = document.createElement("div");
      wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index)).trim();
      const row = wrapper.firstElementChild;
      list.appendChild(row);
      total.value = index + 1;
      bindRow(row);
      row.querySelector("input[name$='-equipment_name']")?.focus();
    });
  };
  window.bindEquipmentItems = bindEquipmentItems;
  bindEquipmentItems();
})();
