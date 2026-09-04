(function () {
  var photos = window.PHOTOS || [];
  var lightbox = document.getElementById("lightbox");
  if (!lightbox) return;

  var img = document.getElementById("lightbox-img");
  var caption = document.getElementById("lightbox-caption");
  var closeBtn = document.getElementById("lightbox-close");
  var prevBtn = document.getElementById("lightbox-prev");
  var nextBtn = document.getElementById("lightbox-next");
  var autoplayBtn = document.getElementById("lightbox-autoplay");
  var startBtn = document.getElementById("slideshow-start");
  var thumbs = document.querySelectorAll(".photo-thumb");

  var current = 0;
  var autoplayTimer = null;
  var AUTOPLAY_MS = 3500;

  function show(index) {
    if (!photos.length) return;
    current = (index + photos.length) % photos.length;
    var p = photos[current];
    img.src = p.full;
    caption.textContent = p.caption || "";
  }

  function open(index) {
    show(index);
    lightbox.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function close() {
    lightbox.hidden = true;
    document.body.style.overflow = "";
    stopAutoplay();
  }

  function next() { show(current + 1); }
  function prev() { show(current - 1); }

  function startAutoplay() {
    stopAutoplay();
    autoplayTimer = setInterval(next, AUTOPLAY_MS);
    autoplayBtn.classList.add("active");
    autoplayBtn.textContent = "Pause";
  }

  function stopAutoplay() {
    if (autoplayTimer) clearInterval(autoplayTimer);
    autoplayTimer = null;
    autoplayBtn.classList.remove("active");
    autoplayBtn.textContent = "Autoplay";
  }

  thumbs.forEach(function (btn) {
    btn.addEventListener("click", function () {
      open(parseInt(btn.dataset.index, 10));
    });
  });

  if (startBtn) {
    startBtn.addEventListener("click", function () {
      open(0);
      startAutoplay();
    });
  }

  closeBtn.addEventListener("click", close);
  nextBtn.addEventListener("click", function () { stopAutoplay(); next(); });
  prevBtn.addEventListener("click", function () { stopAutoplay(); prev(); });
  autoplayBtn.addEventListener("click", function () {
    if (autoplayTimer) stopAutoplay(); else startAutoplay();
  });

  lightbox.addEventListener("click", function (e) {
    if (e.target === lightbox) close();
  });

  document.addEventListener("keydown", function (e) {
    if (lightbox.hidden) return;
    if (e.key === "Escape") close();
    if (e.key === "ArrowRight") { stopAutoplay(); next(); }
    if (e.key === "ArrowLeft") { stopAutoplay(); prev(); }
  });

  // Swipe left/right to navigate on touch devices.
  var touchStartX = null;
  var touchStartY = null;
  var SWIPE_THRESHOLD = 40;

  lightbox.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) return;
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }, { passive: true });

  lightbox.addEventListener("touchend", function (e) {
    if (touchStartX === null) return;
    var touch = e.changedTouches[0];
    var dx = touch.clientX - touchStartX;
    var dy = touch.clientY - touchStartY;
    touchStartX = null;
    touchStartY = null;
    if (Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) < Math.abs(dy)) return;
    stopAutoplay();
    if (dx < 0) next(); else prev();
  }, { passive: true });
})();
