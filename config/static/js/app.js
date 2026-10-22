document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-auto-submit]").forEach((element) => {
        element.addEventListener("change", () => {
            element.closest("form")?.submit();
        });
    });

    document.querySelectorAll("[data-confirm]").forEach((element) => {
        element.addEventListener("click", (event) => {
            const message = element.dataset.confirm;

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});