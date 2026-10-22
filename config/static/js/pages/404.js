(() => {
    "use strict";

    const charactersRoot = document.querySelector("[data-not-found-characters]");
    const canvas = document.querySelector("[data-not-found-canvas]");
    const message = document.querySelector("[data-not-found-message]");
    const backButton = document.querySelector("[data-go-back]");

    if (!charactersRoot || !canvas || !message) return;

    const stickFigures = [
        {
            top: "0%",
            src: "https://cdn.21st.dev/assets/mirror/54/54f366bdbf75b7a2d3b9f2264c3ada12aefcaf6e6a467bcecc856ffcd686e52e.svg",
            transform: "rotateZ(-90deg)",
            speedX: 1500,
        },
        {
            top: "10%",
            src: "https://cdn.21st.dev/assets/mirror/7e/7e48603d6fd3fac9720b25b4b6a06d107feea2d21ef8fa0720921808b9808514.svg",
            speedX: 3000,
            speedRotation: 2000,
        },
        {
            top: "20%",
            src: "https://cdn.21st.dev/assets/mirror/4f/4fd3a604a36cc8811c341ef3221010ed11e2563d4add29901922d7464c28c186.svg",
            speedX: 5000,
            speedRotation: 1000,
        },
        {
            top: "25%",
            src: "https://cdn.21st.dev/assets/mirror/54/54f366bdbf75b7a2d3b9f2264c3ada12aefcaf6e6a467bcecc856ffcd686e52e.svg",
            speedX: 2500,
            speedRotation: 1500,
        },
        {
            top: "35%",
            src: "https://cdn.21st.dev/assets/mirror/54/54f366bdbf75b7a2d3b9f2264c3ada12aefcaf6e6a467bcecc856ffcd686e52e.svg",
            speedX: 2000,
            speedRotation: 300,
        },
        {
            bottom: "5%",
            src: "https://cdn.21st.dev/assets/mirror/66/668d66f4c4d1dbc5c421692b4e5ad644c0f11f0327da214bcae21f78816c6b2f.svg",
            speedX: 0,
        },
    ];

    const animations = [];

    function createCharacters() {
        animations.forEach((animation) => animation.cancel());
        animations.length = 0;
        charactersRoot.replaceChildren();

        stickFigures.forEach((figure, index) => {
            const stick = document.createElement("img");
            stick.className = "not-found__character";
            stick.alt = "";
            stick.draggable = false;
            stick.decoding = "async";
            stick.src = figure.src;

            if (figure.top) stick.style.top = figure.top;
            if (figure.bottom) stick.style.bottom = figure.bottom;
            if (figure.transform) stick.style.transform = figure.transform;

            charactersRoot.appendChild(stick);

            if (index === 5) return;

            animations.push(
                stick.animate(
                    [{ left: "100%" }, { left: "-20%" }],
                    {
                        duration: figure.speedX,
                        easing: "linear",
                        fill: "forwards",
                    },
                ),
            );

            if (index !== 0 && figure.speedRotation) {
                animations.push(
                    stick.animate(
                        [{ transform: "rotate(0deg)" }, { transform: "rotate(-360deg)" }],
                        {
                            duration: figure.speedRotation,
                            iterations: Infinity,
                            easing: "linear",
                        },
                    ),
                );
            }
        });
    }

    const context = canvas.getContext("2d");
    if (!context) {
        message.classList.add("is-visible");
        return;
    }

    let frameId = 0;
    let timer = 0;
    let circles = [];
    let animationRunning = true;
    const mobile = window.matchMedia("(max-width: 640px)").matches;
    const circleCount = mobile ? 220 : 300;

    function initCircles() {
        const width = window.innerWidth;
        const height = window.innerHeight;

        circles = [];

        for (let index = 0; index < circleCount; index += 1) {
            const randomX =
                Math.floor(Math.random() * (width * 3 - width * 1.2 + 1)) +
                width * 1.2;

            const randomY =
                Math.floor(Math.random() * (height - (height * -0.2 + 1))) +
                height * -0.2;

            circles.push({
                x: randomX,
                y: randomY,
                size: width / 1000,
            });
        }
    }

    function draw() {
        if (!animationRunning) return;

        const width = window.innerWidth;
        const height = window.innerHeight;
        const distanceX = width / 80;
        const growthRate = width / 1000;

        timer += 1;

        context.clearRect(0, 0, width, height);
        context.beginPath();

        circles.forEach((circle) => {
            if (timer < 65) {
                circle.x -= distanceX;
                circle.size += growthRate;
            }

            if (timer > 65 && timer < 500) {
                circle.x -= distanceX * 0.02;
                circle.size += growthRate * 0.2;
            }

            context.moveTo(circle.x + circle.size, circle.y);
            context.arc(circle.x, circle.y, circle.size, 0, Math.PI * 2);
        });

        context.fill();

        if (timer > 500) {
            frameId = 0;
            return;
        }

        frameId = requestAnimationFrame(draw);
    }

    function restartCanvas() {
        if (frameId) cancelAnimationFrame(frameId);
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        context.fillStyle = "white";
        timer = 0;
        animationRunning = true;
        initCircles();
        draw();
    }

    function stopAnimation() {
        animationRunning = false;
        if (frameId) {
            cancelAnimationFrame(frameId);
            frameId = 0;
        }
    }

    backButton?.addEventListener("click", () => {
        if (window.history.length > 1) {
            window.history.back();
        } else {
            window.location.assign("/");
        }
    });

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (!reducedMotion) {
        createCharacters();
        restartCanvas();
    }

    window.setTimeout(() => {
        message.classList.add("is-visible");
    }, reducedMotion ? 0 : 1200);

    let resizeTimer = 0;

    window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
            if (!reducedMotion) {
                createCharacters();
                restartCanvas();
            }
        }, 120);
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopAnimation();
        } else if (!reducedMotion && timer < 500) {
            animationRunning = true;
            frameId = requestAnimationFrame(draw);
        }
    });

    window.addEventListener("pagehide", () => {
        stopAnimation();
        animations.forEach((animation) => animation.cancel());
    });
})();
