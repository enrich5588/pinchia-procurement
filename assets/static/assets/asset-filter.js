document.querySelectorAll("[data-auto-submit]").forEach((form) => {
  form.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => {
      if (form.classList.contains("is-submitting")) return;
      form.classList.add("is-submitting");
      form.requestSubmit();
    });
  });
});
