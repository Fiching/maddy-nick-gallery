# Maddy & Nick's Gallery

A small photo gallery/slideshow site, gated behind a single shared password
for both viewing and uploading. Built with Flask; photo storage, resizing,
and delivery is handled by Cloudinary's free tier, so the app itself is
completely stateless and can run on Render's free plan.

## How it works

- Albums are just Cloudinary folders under `albums/<slug>/`. Creating a new
  album is done from the Upload page — no code changes or redeploys needed.
- The whole site — viewing and uploading — requires logging in with one
  shared password (`UPLOAD_PASSWORD`).
- Uploads go straight from the browser to Cloudinary (the Flask app only
  hands out a short-lived signed upload request per photo). This app's
  server never sees the photo bytes, so a big batch can't hit its request
  size or timeout limits — see `static/upload.js` and the `/upload/sign`
  route in `app.py` if you're changing how uploads work.
- Cloudinary auto-generates resized, optimized versions of every photo for
  the grid and the full-screen slideshow (and converts iPhone HEIC photos to
  something every browser can display).
- The homepage shows a random photo from a random album as a hero banner.
  Each album has controls to rename it, reorder photos, set a cover photo,
  and delete a photo or the whole album (with a confirmation on every
  delete).

## Run it locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in the values (see below)
python app.py
```

Visit http://localhost:5000

## One-time setup

1. **Cloudinary account** (free): sign up at cloudinary.com, then copy your
   Cloud Name, API Key, and API Secret from the dashboard into `.env`
   (locally) or your host's environment variables (in production).
2. **Pick a shared password** for `UPLOAD_PASSWORD` — this is what you and
   Maddy will use to log in and upload.
3. **Set `SECRET_KEY`** to any random string (used to sign login sessions).

## Deploying to Render (same flow as your other projects)

1. Push this folder to a new GitHub repo.
2. In Render: New → Web Service → connect the repo.
   - Runtime: Python
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Plan: Free
3. Add the environment variables from `.env.example` (with real values) in
   the Render dashboard under Environment — don't commit real secrets to
   the repo.
4. Deploy. Your site will be live at `https://<service-name>.onrender.com`.
   Add a custom domain later from the Render dashboard once you've bought
   one, if you want.

Note: Render's free plan spins the service down after 15 minutes of no
traffic and takes ~30-60 seconds to wake back up on the next visit. Since
all photos live in Cloudinary (not on the Render instance), nothing is ever
lost when it spins down — only the wake-up delay is noticeable.

## Adding future albums

Just go to `/upload`, log in, and either pick an existing album or type a
new album name (e.g. "Outer Banks 2027") — it's created automatically on
first upload. No code changes required.

## Ideas for later (not built yet)

- Per-photo captions (currently one caption applies to a whole upload batch)
- Downloading a whole album as a zip
- Drag-and-drop photo reordering (currently move-earlier/move-later buttons)
