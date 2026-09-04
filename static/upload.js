(function () {
  var form = document.getElementById("upload-form");
  if (!form) return;

  var submitBtn = document.getElementById("upload-submit");
  var progressWrap = document.getElementById("upload-progress");
  var progressBar = document.getElementById("upload-progress-bar");
  var progressLabel = document.getElementById("upload-progress-label");

  form.addEventListener("submit", function (e) {
    var filesInput = document.getElementById("files");
    if (!filesInput.files.length) return; // let native validation handle it

    // XMLHttpRequest lets us show real upload progress; fall back to a
    // normal form submit if something unexpected goes wrong.
    if (typeof XMLHttpRequest === "undefined") return;

    e.preventDefault();

    var formData = new FormData(form);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", window.location.pathname, true);

    xhr.upload.addEventListener("progress", function (evt) {
      if (!evt.lengthComputable) return;
      var pct = Math.round((evt.loaded / evt.total) * 100);
      progressBar.style.width = pct + "%";
      progressLabel.textContent = "Uploading… " + pct + "%";
    });

    xhr.addEventListener("load", function () {
      if (xhr.status >= 200 && xhr.status < 400) {
        window.location = xhr.responseURL || window.location.pathname;
      } else {
        progressLabel.textContent = "Something went wrong — please try again.";
        submitBtn.disabled = false;
        submitBtn.textContent = "Upload";
      }
    });

    xhr.addEventListener("error", function () {
      progressLabel.textContent = "Upload failed — check your connection and try again.";
      submitBtn.disabled = false;
      submitBtn.textContent = "Upload";
    });

    submitBtn.disabled = true;
    submitBtn.textContent = "Uploading…";
    progressWrap.hidden = false;
    progressBar.style.width = "0%";
    progressLabel.textContent = "Uploading…";
    xhr.send(formData);
  });
})();
