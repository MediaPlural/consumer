# Platform recipe: skool.com

> Status: wired into `course-dl.py`, live-tested against public communities.
> Gated classrooms need your member cookie — this tool never breaks auth.

## What skool is, structurally

- Communities at `skool.com/{community}`; courses live in `/classroom`, lessons
  at `skool.com/{community}/classroom/{course-id}?md={32-hex-id}`.
- **The classroom page renders server-side** (course cards, titles, progress)
  — the crawler captures it without JS. Lesson lists inside a course render
  for members only.
- Videos are embeds (Cloudflare Stream / Mux / Loom / YouTube / Vimeo) and
  are hotlink-protected: downloads need the skool referer (course-dl adds it
  automatically) + your session cookies.

## How to consume a skool course you're a member of

1. **Export cookies** for `skool.com` from your logged-in browser:
   - Chrome: extension "Get cookies.txt" (or `yt-dlp --cookies-from-browser chrome`)
   - The Netscape-format file is what `--cookies` expects.
2. **Run**:
   ```bash
   python3 course-dl.py "https://www.skool.com/YOUR-COMMUNITY/classroom" \
       --out-dir ./my-course --cookies skool-cookies.txt --max-pages 300
   ```
3. What happens:
   - Every classroom/course page is captured to `pages/` (text extracted).
   - Lesson URLs (`?md=…` hashes) are harvested from page source and queued.
   - Lesson videos are downloaded via yt-dlp with `--referer https://www.skool.com`.
   - Attachments (PDFs, links) land in `files/`; everything is fingerprinted
     in `acquisition.json`.
4. Then transcribe + distill as usual:
   ```bash
   python3 consumer.py ./my-course/media --tag my-course
   ```

## Gotchas (earned)

- **"Unlock at Level 1"**: even free public communities gate courses behind
  joining. Join first, then export cookies — the classroom tree appears for
  members.
- **Free-tier pages crawl fine without login**: community/classroom/calendar/
  members pages capture; course _interiors_ don't.
- **Cloudflare Stream 403 without referer**: course-dl's `save_media` adds
  `--referer https://www.skool.com` on skool URLs automatically.
- **Lesson titles are thin**: `?md=` pages render title + description for
  members; the meat is the video — transcription is where the content becomes
  text.
- If yt-dlp fails on a lesson, try `yt-dlp --cookies-from-browser chrome
"<lesson-url>"` manually first — browser-cookies solve most 403s.

## Verified (2026-10-06, this recipe's first run)

- Public community `skool.com/admins`: 6 pages captured incl. server-rendered
  classroom cards — without login.
- md= harvest + referer handling: in-course (needs a member session to
  exercise end-to-end).

## Credential handling (the segmented store)

Never paste cookies into the command line. Use the store:

```bash
python3 creds.py init skool                    # create the 0700 slot
python3 creds.py import skool cookies.txt      # move your jar in (0600, source removed)
python3 creds.py verify skool                  # counts + freshness — never values
python3 course-dl.py "https://www.skool.com/YOUR-COMMUNITY/classroom" \
    --platform skool --out-dir ./my-course      # broker attaches creds at the boundary
```

The pipeline never touches credential material: creds.Broker is the only code
that reads the store, cookies attach inside the network boundary, and the
acquisition manifest records only the identity (`platform:skool`).
