(function () {
  var form = document.getElementById("upload-form");
  if (!form) return;

  var ALLOWED = ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif"];
  var CONCURRENCY = 3; // a few photos in flight at once, without overwhelming a phone's upload speed

  var submitBtn = document.getElementById("upload-submit");
  var progressWrap = document.getElementById("upload-progress");
  var progressBar = document.getElementById("upload-progress-bar");
  var progressLabel = document.getElementById("upload-progress-label");
  var openAlbumLink = document.getElementById("upload-open-album");
  var filesInput = document.getElementById("files");

  var retryQueue = null; // set when a batch finishes with some failures

  function extOf(name) {
    var i = name.lastIndexOf(".");
    return i === -1 ? "" : name.slice(i + 1).toLowerCase();
  }

  function formValues() {
    return {
      new_album_title: document.getElementById("new_album_title").value.trim(),
      existing_album: document.getElementById("existing_album").value.trim(),
      caption: document.getElementById("caption").value.trim(),
    };
  }

  // Ask our own server for a signed, short-lived set of upload parameters.
  // We fetch a fresh one per photo rather than sharing one across the whole
  // batch, so a slow connection on photo #40 of 150 can never run into a
  // stale/expired signature.
  function requestSignature() {
    return fetch("/upload/sign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formValues()),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) throw new Error(data.error || "Could not start the upload.");
        return data;
      });
    });
  }

  // Upload one file straight to Cloudinary -- this app's server is never in
  // the path for the actual photo bytes.
  function uploadOne(file, sig, onProgress) {
    return new Promise(function (resolve, reject) {
      var url = "https://api.cloudinary.com/v1_1/" + sig.cloud_name + "/image/upload";
      var fd = new FormData();
      fd.append("file", file);
      fd.append("api_key", sig.api_key);
      fd.append("timestamp", sig.timestamp);
      fd.append("signature", sig.signature);
      fd.append("folder", sig.folder);
      fd.append("use_filename", sig.use_filename);
      fd.append("unique_filename", sig.unique_filename);
      fd.append("overwrite", sig.overwrite);
      if (sig.context) fd.append("context", sig.context);

      var xhr = new XMLHttpRequest();
      xhr.open("POST", url, true);

      xhr.upload.addEventListener("progress", function (evt) {
        if (evt.lengthComputable) onProgress(evt.loaded);
      });
      xhr.addEventListener("load", function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress(file.size);
          resolve();
        } else {
          reject(new Error("Cloudinary rejected " + file.name));
        }
      });
      xhr.addEventListener("error", function () {
        reject(new Error("Network error uploading " + file.name));
      });

      xhr.send(fd);
    });
  }

  function resetButton(label) {
    submitBtn.disabled = false;
    submitBtn.textContent = label;
  }

  function runBatch(files, skippedCount) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Uploading…";
    progressWrap.hidden = false;
    progressBar.style.width = "0%";
    if (openAlbumLink) openAlbumLink.hidden = true;
    progressLabel.textContent = skippedCount
      ? "Starting… (" + skippedCount + " file(s) skipped — unsupported type)"
      : "Starting…";

    var totalBytes = files.reduce(function (sum, f) { return sum + f.size; }, 0) || 1;
    var loaded = files.map(function () { return 0; });
    var failed = [];
    var succeededCount = 0;
    var finishedCount = 0;
    var slug = null;
    var nextIndex = 0;

    function updateProgress() {
      var loadedTotal = loaded.reduce(function (a, b) { return a + b; }, 0);
      var pct = Math.min(100, Math.round((loadedTotal / totalBytes) * 100));
      progressBar.style.width = pct + "%";
      progressLabel.textContent =
        "Uploading… " + pct + "% (" + finishedCount + " of " + files.length + " photos" +
        (failed.length ? ", " + failed.length + " failed" : "") + ")";
    }

    function worker() {
      if (nextIndex >= files.length) return Promise.resolve();
      var i = nextIndex++;
      var file = files[i];

      return requestSignature()
        .then(function (sig) {
          slug = sig.slug;
          return uploadOne(file, sig, function (loadedBytes) {
            loaded[i] = loadedBytes;
            updateProgress();
          });
        })
        .then(function () {
          succeededCount++;
        })
        .catch(function () {
          loaded[i] = file.size;
          failed.push(file);
        })
        .then(function () {
          finishedCount++;
          updateProgress();
          return worker();
        });
    }

    function finish() {
      if (!failed.length) {
        progressLabel.textContent = "Uploaded " + succeededCount + " photo(s). Opening album…";
        window.location = "/album/" + slug;
        return;
      }

      progressLabel.textContent = succeededCount + " of " + files.length + " uploaded, " +
        failed.length + " failed. The ones that made it are already saved — retry just the rest, or open the album now.";
      retryQueue = failed;
      resetButton("Retry " + failed.length + " failed photo" + (failed.length === 1 ? "" : "s"));

      if (openAlbumLink && slug) {
        openAlbumLink.href = "/album/" + slug;
        openAlbumLink.hidden = false;
      }
    }

    requestSignature().then(
      function (sig) {
        slug = sig.slug;
        var workers = [];
        for (var w = 0; w < Math.min(CONCURRENCY, files.length); w++) {
          workers.push(worker());
        }
        Promise.all(workers).then(finish);
      },
      function (err) {
        progressLabel.textContent = err.message;
        resetButton("Upload");
      }
    );
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (submitBtn.disabled) return;

    if (retryQueue) {
      var toRetry = retryQueue;
      retryQueue = null;
      runBatch(toRetry, 0);
      return;
    }

    var all = Array.prototype.slice.call(filesInput.files);
    if (!all.length) return;

    var files = all.filter(function (f) { return ALLOWED.indexOf(extOf(f.name)) !== -1; });
    var skipped = all.length - files.length;

    if (!files.length) {
      progressWrap.hidden = false;
      progressLabel.textContent = "None of those look like supported photo files.";
      return;
    }

    runBatch(files, skipped);
  });
})();
