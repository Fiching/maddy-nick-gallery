import os
import re
import time
import logging
import functools
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort
)

import cloudinary
import cloudinary.uploader
import cloudinary.api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maddy-nick-gallery")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB per request (batch uploads)

SITE_TITLE = os.environ.get("SITE_TITLE", "Maddy & Nick")
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD")

CLOUDINARY_CONFIGURED = all(
    os.environ.get(k) for k in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
)

if CLOUDINARY_CONFIGURED:
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )

ALBUMS_ROOT = "albums"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif"}

_usage_cache = {"percent": None, "checked_at": 0}
USAGE_CACHE_SECONDS = 30 * 60  # only check Cloudinary's usage API every 30 minutes


# ---------- helpers ----------

def slugify(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def prettify(slug):
    return slug.replace("-", " ").title()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def list_albums():
    """Return a list of {slug, title, cover_url} dicts, newest first."""
    if not CLOUDINARY_CONFIGURED:
        return []
    try:
        result = cloudinary.api.subfolders(ALBUMS_ROOT)
    except cloudinary.exceptions.NotFound:
        return []
    except Exception:
        return []

    albums = []
    for folder in result.get("folders", []):
        slug = folder["name"]
        cover_url = get_cover_url(slug)
        albums.append({
            "slug": slug,
            "title": prettify(slug),
            "cover_url": cover_url,
        })
    # newest-created album first, approximated by reverse alpha of slug's
    # trailing date-ish tokens falling back to name; simplest stable option:
    albums.sort(key=lambda a: a["slug"], reverse=True)
    return albums


def get_cover_url(slug, width=500, height=375):
    try:
        res = cloudinary.api.resources(
            type="upload", prefix=f"{ALBUMS_ROOT}/{slug}/", max_results=1
        )
        resources = res.get("resources", [])
        if not resources:
            return None
        public_id = resources[0]["public_id"]
        return cloudinary.CloudinaryImage(public_id).build_url(
            width=width, height=height, crop="fill", quality="auto", fetch_format="auto"
        )
    except Exception:
        return None


def list_photos(slug):
    """Return list of {thumb_url, full_url, caption} for an album, oldest first."""
    if not CLOUDINARY_CONFIGURED:
        return []
    try:
        res = cloudinary.api.resources(
            type="upload", prefix=f"{ALBUMS_ROOT}/{slug}/",
            max_results=500, context=True,
        )
    except Exception:
        return []

    photos = []
    for r in res.get("resources", []):
        public_id = r["public_id"]
        context = r.get("context", {}).get("custom", {}) if r.get("context") else {}
        photos.append({
            "public_id": public_id,
            "thumb_url": cloudinary.CloudinaryImage(public_id).build_url(
                width=400, height=400, crop="fill", quality="auto", fetch_format="auto"
            ),
            "full_url": cloudinary.CloudinaryImage(public_id).build_url(
                width=1800, crop="limit", quality="auto", fetch_format="auto"
            ),
            "caption": context.get("caption", ""),
            "created_at": r.get("created_at", ""),
        })
    photos.sort(key=lambda p: p["created_at"])
    return photos


def get_storage_percent():
    """Return an int 0-100 for how much of the Cloudinary free monthly plan
    has been used (storage + bandwidth + transformations combined, per
    Cloudinary's own 'credits' figure), or None if unknown. Cached for
    USAGE_CACHE_SECONDS so we don't hit Cloudinary's Admin API on every
    page view."""
    if not CLOUDINARY_CONFIGURED:
        return None

    now = time.time()
    if _usage_cache["percent"] is not None and now - _usage_cache["checked_at"] < USAGE_CACHE_SECONDS:
        return _usage_cache["percent"]

    try:
        usage = cloudinary.api.usage()
        pct = usage.get("credits", {}).get("used_percent")
        if pct is None:
            return _usage_cache["percent"]  # stale-but-known beats nothing
        pct = max(0, min(100, round(pct)))
        _usage_cache["percent"] = pct
        _usage_cache["checked_at"] = now
        return pct
    except Exception:
        logger.exception("Could not fetch Cloudinary usage")
        return _usage_cache["percent"]


# ---------- routes ----------

@app.context_processor
def inject_globals():
    return {
        "site_title": SITE_TITLE,
        "storage_percent": get_storage_percent() if session.get("authed") else None,
    }


@app.route("/")
def index():
    if not CLOUDINARY_CONFIGURED:
        flash(
            "Photo storage isn't configured yet. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET (see README).",
            "warning",
        )
    albums = list_albums()
    return render_template("index.html", albums=albums)


@app.route("/album/<slug>")
def album(slug):
    slug = slugify(slug)
    photos = list_photos(slug)
    if not photos and not CLOUDINARY_CONFIGURED:
        abort(404)
    return render_template("album.html", slug=slug, title=prettify(slug), photos=photos)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if UPLOAD_PASSWORD and request.form.get("password") == UPLOAD_PASSWORD:
            session["authed"] = True
            next_url = request.args.get("next") or url_for("upload")
            return redirect(next_url)
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("index"))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        if not CLOUDINARY_CONFIGURED:
            flash("Photo storage isn't configured yet — see README.", "error")
            return redirect(url_for("upload"))

        new_title = request.form.get("new_album_title", "").strip()
        existing_slug = request.form.get("existing_album", "").strip()
        caption = request.form.get("caption", "").strip()

        if new_title:
            slug = slugify(new_title)
        elif existing_slug:
            slug = existing_slug
        else:
            flash("Choose an existing album or name a new one.", "error")
            return redirect(url_for("upload"))

        if not slug:
            flash("That album name didn't work — try letters and numbers.", "error")
            return redirect(url_for("upload"))

        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("Pick at least one photo to upload.", "error")
            return redirect(url_for("upload"))

        uploaded, skipped = 0, 0
        for f in files:
            if not allowed_file(f.filename):
                skipped += 1
                continue
            try:
                cloudinary.uploader.upload(
                    f,
                    folder=f"{ALBUMS_ROOT}/{slug}",
                    use_filename=True,
                    unique_filename=True,
                    overwrite=False,
                    context={"caption": caption} if caption else None,
                )
                uploaded += 1
            except Exception:
                logger.exception("Upload failed for file %r in album %r", f.filename, slug)
                skipped += 1

        if uploaded:
            flash(f"Uploaded {uploaded} photo(s) to \"{prettify(slug)}\".", "success")
        if skipped:
            flash(f"Skipped {skipped} file(s) (unsupported type or upload error).", "warning")

        return redirect(url_for("album", slug=slug))

    albums = list_albums()
    return render_template("upload.html", albums=albums)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
