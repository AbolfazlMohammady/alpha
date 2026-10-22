document.addEventListener("DOMContentLoaded", () => {
    const body = document.body;

    /*
     * =========================================================
     * HEADER SCROLL STATE
     * =========================================================
     */

    const header = document.querySelector(".site-header");

    const updateHeader = () => {
        if (!header) {
            return;
        }

        if (window.scrollY > 30) {
            header.classList.add("is-scrolled");
        } else {
            header.classList.remove("is-scrolled");
        }
    };

    updateHeader();

    window.addEventListener(
        "scroll",
        updateHeader,
        { passive: true }
    );


    /*
     * =========================================================
     * MOBILE MENU
     * =========================================================
     */

    const mobileMenu = document.querySelector(
        "[data-mobile-menu-panel]"
    );

    const mobileMenuTriggers = document.querySelectorAll(
        "[data-mobile-menu]"
    );

    const mobileMenuCloseButtons = document.querySelectorAll(
        "[data-mobile-menu-close]"
    );


    const openMobileMenu = () => {
        if (!mobileMenu) {
            return;
        }

        mobileMenu.classList.add("is-open");

        mobileMenu.setAttribute(
            "aria-hidden",
            "false"
        );

        body.classList.add("no-scroll");

        mobileMenuTriggers.forEach((trigger) => {
            trigger.setAttribute(
                "aria-expanded",
                "true"
            );
        });
    };


    const closeMobileMenu = () => {
        if (!mobileMenu) {
            return;
        }

        mobileMenu.classList.remove("is-open");

        mobileMenu.setAttribute(
            "aria-hidden",
            "true"
        );

        body.classList.remove("no-scroll");

        mobileMenuTriggers.forEach((trigger) => {
            trigger.setAttribute(
                "aria-expanded",
                "false"
            );
        });
    };


    mobileMenuTriggers.forEach((trigger) => {
        trigger.addEventListener(
            "click",
            openMobileMenu
        );
    });


    mobileMenuCloseButtons.forEach((button) => {
        button.addEventListener(
            "click",
            closeMobileMenu
        );
    });


    mobileMenu?.querySelectorAll("a").forEach((link) => {
        link.addEventListener(
            "click",
            closeMobileMenu
        );
    });


    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeMobileMenu();
        }
    });


    /*
     * =========================================================
     * MODALS
     * =========================================================
     */

    document.querySelectorAll(
        "[data-modal-open]"
    ).forEach((trigger) => {

        trigger.addEventListener("click", () => {

            const selector =
                trigger.dataset.modalOpen;

            const modal =
                document.querySelector(selector);

            if (!modal) {
                return;
            }

            modal.classList.add("is-open");

            body.classList.add("no-scroll");
        });
    });


    document.querySelectorAll(
        "[data-modal-close]"
    ).forEach((trigger) => {

        trigger.addEventListener("click", () => {

            const modal =
                trigger.closest(".modal");

            if (!modal) {
                return;
            }

            modal.classList.remove("is-open");

            body.classList.remove("no-scroll");
        });
    });
});
