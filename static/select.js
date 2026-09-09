(function () {
  var grid = document.getElementById("photo-grid");
  if (!grid) return;

  var selectToggleBtn = document.getElementById("select-toggle");
  var selectBar = document.getElementById("select-bar");
  var selectAllCheckbox = document.getElementById("select-all-checkbox");
  var selectCount = document.getElementById("select-count");
  var downloadBtn = document.getElementById("select-download-btn");
  var downloadForm = document.getElementById("select-download-form");

  var tiles = Array.prototype.slice.call(grid.querySelectorAll(".photo-tile"));
  var selected = new Set();
  var selecting = false;

  function updateCount() {
    selectCount.textContent = selected.size + " selected";
    downloadBtn.disabled = selected.size === 0;
    if (selectAllCheckbox) {
      selectAllCheckbox.checked = selected.size > 0 && selected.size === tiles.length;
      selectAllCheckbox.indeterminate = selected.size > 0 && selected.size < tiles.length;
    }
  }

  function toggleTile(tile, force) {
    var id = tile.dataset.publicId;
    var cb = tile.querySelector(".select-checkbox");
    var shouldSelect = typeof force === "boolean" ? force : !selected.has(id);

    if (shouldSelect) {
      selected.add(id);
      tile.classList.add("selected");
    } else {
      selected.delete(id);
      tile.classList.remove("selected");
    }
    if (cb) cb.checked = shouldSelect;
    updateCount();
  }

  function setSelecting(on) {
    selecting = on;
    grid.classList.toggle("selecting", on);
    selectBar.hidden = !on;
    selectToggleBtn.textContent = on ? "Cancel" : "Select photos";
    if (!on) {
      tiles.forEach(function (t) { toggleTile(t, false); });
    }
  }

  selectToggleBtn.addEventListener("click", function () {
    setSelecting(!selecting);
  });

  tiles.forEach(function (tile) {
    var cb = tile.querySelector(".select-checkbox");
    if (cb) {
      cb.addEventListener("change", function () {
        toggleTile(tile, cb.checked);
      });
    }
  });

  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", function () {
      var shouldSelectAll = selectAllCheckbox.checked;
      tiles.forEach(function (tile) { toggleTile(tile, shouldSelectAll); });
    });
  }

  // Intercept taps on the thumbnail itself while in select mode, before
  // lightbox.js's own click handler (registered later, in the bubble
  // phase) gets a chance to open the full-screen viewer instead.
  document.addEventListener("click", function (e) {
    if (!selecting) return;
    var btn = e.target.closest && e.target.closest(".photo-thumb");
    if (!btn) return;
    var tile = btn.closest(".photo-tile");
    if (!tile) return;
    e.stopPropagation();
    e.preventDefault();
    toggleTile(tile);
  }, true);

  downloadBtn.addEventListener("click", function () {
    if (!selected.size) return;

    if (selected.size === 1) {
      var onlyId = selected.values().next().value;
      var tile = tiles.filter(function (t) { return t.dataset.publicId === onlyId; })[0];
      if (tile && tile.dataset.downloadUrl) {
        window.location = tile.dataset.downloadUrl;
        return;
      }
    }

    // More than one photo: Cloudinary builds a zip on the fly for us: the
    // server just needs the list of public_ids to sign the request for.
    downloadForm.innerHTML = "";
    selected.forEach(function (id) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "public_ids";
      input.value = id;
      downloadForm.appendChild(input);
    });
    downloadForm.submit();
  });
})();
