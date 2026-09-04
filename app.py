import os
import re
import time
import random
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

_hero_cache = {"photo": None, "checked_at": 0}
HERO_CACHE_SECONDS = 5 * 60  # rotate the homepage hero photo every 5 minutes, not every load


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


def album_exists(slug):
    try:
        res = cloudinary.api.resources(type="upload", prefix=f"{ALBUMS_ROOT}/{slug}/", max_results=1)
        return len(res.get("resources", [])) > 0
    except Exception:
        return False


def list_albums():
    """Return a list of {slug, title, cover_url} dicts, newest first."""
    if not CLOUDINARY_CONFIGURED:
        return []
    try:
        result = cloudinary.api.subfolders(ALBUMS_ROOT)
    except cloudinary.exceptions.NotFound:
        return []
    except Exception:
        logger.exception("Could not list albums")
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
            type="upload", prefix=f"{ALBUMS_ROOT}/{slug}/", max_results=30, context=True,
        )
        resources = res.get("resources", [])
        if not resources:
            return None
        chosen = None
        for r in resources:
            ctx = r.get("context", {}).get("custom", {}) if r.get("context") else {}
            if ctx.get("is_cover") == "1":
                chosen = r
                break
        if chosen is None:
            chosen = resources[0]
        public_id = chosen["public_id"]
        return cloudinary.CloudinaryImage(public_id).build_url(
            width=width, height=height, crop="fill", quality="auto", fetch_format="auto"
        )
    except Exception:
        return None


def list_photos(slug):
    """Return list of photo dicts for an album, respecting manual ordering
    once any photo in the album has been explicitly reordered; otherwise
    falls back to upload order (oldest first)."""
    if not CLOUDINARY_CONFIGURED:
        return []
    try:
        res = cloudinary.api.resources(
            type="upload", prefix=f"{ALBUMS_ROOT}/{slug}/",
            max_results=500, context=True,
        )
    except Exception:
        logger.exception("Could not list photos for album %r", slug)
        return []

    photos = []
    for r in res.get("resources", []):
        public_id = r["public_id"]
        ctx = r.get("context", {}).get("custom", {}) if r.get("context") else {}
        position = ctx.get("position")
        photos.append({
            "public_id": public_id,
            "thumb_url": cloudinary.CloudinaryImage(public_id).build_url(
                width=400, height=400, crop="fill", quality="auto", fetch_format="auto"
            ),
            "full_url": cloudinary.CloudinaryImage(public_id).build_url(
                width=1800, crop="limit", quality="auto", fetch_format="auto"
            ),
            "caption": ctx.get("caption", ""),
            "is_cover": ctx.get("is_cover") == "1",
            "position": int(position) if position not in (None, "") else None,
            "created_at": r.get("created_at", ""),
        })

    # base order: upload/creation time
    photos.sort(key=lambda p: p["created_at"])

    # if reordering has ever been used in this album, overlay it: photos
    # without an explicit position keep their current chronological slot
    if any(p["position"] is not None for p in photos):
        for i, p in enumerate(photos):
            if p["position"] is None:
                p["position"] = i
        photos.sort(key=lambda p: p["position"])

    return photos


def update_photo_fields(public_id, **updates):
    """Merge the given fields into a photo's existing context metadata
    (so setting e.g. position doesn't wipe out an existing caption)."""
    try:
        current = cloudinary.api.resource(public_id, context=True)
        context = current.get("context", {}).get("custom", {}) if current.get("context") else {}
    except Exception:
        logger.exception("Could not read existing context for %r", public_id)
        context = {}
    context = dict(context)
    for k, v in updates.items():
        if v is None:
            context.pop(k, None)
        else:
            context[k] = str(v)
    cloudinary.api.update(public_id, context=context)


def get_random_hero():
    """Pick a random photo from a random album to feature on the homepage.
    Cached briefly so it doesn't refetch every single page view."""
    if not CLOUDINARY_CONFIGURED:
        return None

    now = time.time()
    if _hero_cache["photo"] is not None and now - _hero_cache["checked_at"] < HERO_CACHE_SECONDS:
        return _hero_cache["photo"]

    albums = list_albums()
    candidates = list(albums)
    random.shuffle(candidates)
    for a in candidates:
        photos = list_photos(a["slug"])
        if photos:
            p = random.choice(photos)
            hero = {
                "url": cloudinary.CloudinaryImage(p["public_id"]).build_url(
                    width=1600, crop="limit", quality="auto", fetch_format="auto"
                ),
                "slug": a["slug"],
                "album_title": a["title"],
                "caption": p["caption"],
            }
            _hero_cache["photo"] = hero
            _hero_cache["checked_at"] = now
            return hero

    _hero_cache["photo"] = None
    _hero_cache["checked_at"] = now
    return None


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
@login_required
def index():
    if not CLOUDINARY_CONFIGURED:
        flash(
            "Photo storage isn't configured yet. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET (see README).",
            "warning",
        )
    albums = list_albums()
    hero = get_random_hero()
    return render_template("index.html", albums=albums, hero=hero)


@app.route("/album/<slug>")
@login_required
def album(slug):
    slug = slugify(slug)
    photos = list_photos(slug)
    if not photos and not album_exists(slug):
        abort(404)
    return render_template("album.html", slug=slug, title=prettify(slug), photos=photos)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if UPLOAD_PASSWORD and request.form.get("password") == UPLOAD_PASSWORD:
            session["authed"] = True
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("login"))


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


@app.route("/album/<slug>/rename", methods=["POST"])
@login_required
def rename_album(slug):
    slug = slugify(slug)
    new_title = request.form.get("new_title", "").strip()
    new_slug = slugify(new_title)

    if not new_slug:
        flash("Enter a valid new name.", "error")
        return redirect(url_for("album", slug=slug))

    if new_slug == slug:
        return redirect(url_for("album", slug=slug))

    if album_exists(new_slug):
        flash(f"An album called \"{prettify(new_slug)}\" already exists.", "error")
        return redirect(url_for("album", slug=slug))

    try:
        photos = list_photos(slug)
        for p in photos:
            new_public_id = p["public_id"].replace(
                f"{ALBUMS_ROOT}/{slug}/", f"{ALBUMS_ROOT}/{new_slug}/", 1
            )
            cloudinary.uploader.rename(p["public_id"], new_public_id)
        try:
            cloudinary.api.delete_folder(f"{ALBUMS_ROOT}/{slug}")
        except Exception:
            pass  # cosmetic cleanup only; an empty leftover folder is harmless
        flash(f"Renamed to \"{prettify(new_slug)}\".", "success")
        return redirect(url_for("album", slug=new_slug))
    except Exception:
        logger.exception("Rename failed for album %r -> %r", slug, new_slug)
        flash("Something went wrong renaming that album — nothing was changed.", "error")
        return redirect(url_for("album", slug=slug))


@app.route("/album/<slug>/delete", methods=["POST"])
@login_required
def delete_album(slug):
    slug = slugify(slug)
    try:
        cloudinary.api.delete_resources_by_prefix(f"{ALBUMS_ROOT}/{slug}/")
        try:
            cloudinary.api.delete_folder(f"{ALBUMS_ROOT}/{slug}")
        except Exception:
            pass
        flash(f"Deleted \"{prettify(slug)}\" and all its photos.", "success")
    except Exception:
        logger.exception("Delete failed for album %r", slug)
        flash("Something went wrong deleting that album.", "error")
    return redirect(url_for("index"))


@app.route("/album/<slug>/photo/<path:public_id>/delete", methods=["POST"])
@login_required
def delete_photo(slug, public_id):
    slug = slugify(slug)
    try:
        cloudinary.api.delete_resources([public_id])
        flash("Photo deleted.", "success")
    except Exception:
        logger.exception("Could not delete photo %r", public_id)
        flash("Couldn't delete that photo.", "error")
    return redirect(url_for("album", slug=slug))


@app.route("/album/<slug>/photo/<path:public_id>/move", methods=["POST"])
@login_required
def move_photo(slug, public_id):
    slug = slugify(slug)
    direction = request.form.get("direction")
    photos = list_photos(slug)
    # Backfill implicit positions (None) with each photo's current index so
    # the swap below always writes explicit values, even in an album that
    # has never been manually reordered before (otherwise swapping two
    # None/None positions is a silent no-op).
    effective = [p["position"] if p["position"] is not None else i for i, p in enumerate(photos)]
    idx = next((i for i, p in enumerate(photos) if p["public_id"] == public_id), None)

    if idx is not None:
        other = idx - 1 if direction == "up" else idx + 1 if direction == "down" else None
        if other is not None and 0 <= other < len(photos):
            try:
                pos_a, pos_b = effective[idx], effective[other]
                update_photo_fields(photos[idx]["public_id"], position=pos_b)
                update_photo_fields(photos[other]["public_id"], position=pos_a)
            except Exception:
                logger.exception("Could not reorder photo %r", public_id)
                flash("Couldn't reorder that photo.", "error")

    return redirect(url_for("album", slug=slug))


@app.route("/album/<slug>/photo/<path:public_id>/cover", methods=["POST"])
@login_required
def set_cover(slug, public_id):
    slug = slugify(slug)
    try:
        for p in list_photos(slug):
            if p["is_cover"] and p["public_id"] != public_id:
                update_photo_fields(p["public_id"], is_cover=None)
        update_photo_fields(public_id, is_cover="1")
        flash("Album cover updated.", "success")
    except Exception:
        logger.exception("Could not set cover %r", public_id)
        flash("Couldn't set that as the cover photo.", "error")
    return redirect(url_for("album", slug=slug))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
