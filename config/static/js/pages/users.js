document.addEventListener("DOMContentLoaded", () => {
    const phoneInput = document.querySelector(".auth-phone-input");

    if (!phoneInput) return;

    phoneInput.addEventListener("input", () => {
        phoneInput.value = phoneInput.value.replace(/\D/g, "").slice(0, 11);
    });
});
