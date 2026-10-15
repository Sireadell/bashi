# Deploy Bashi (about 10 minutes)

Hosting choice: Render free web service using the Dockerfile, because it needs no build settings beyond the file already in the repo and the free tier gives a public https link.

You need: the GitHub repo with these files, a Render account, and the four FalkorDB Cloud connection values (host, port, username, password).

## Part 1: put the site online

1. Go to render.com and sign in with GitHub.
2. Click **New +**, then **Web Service**.
3. Pick the Bashi repository. Click **Connect**.
4. Language: **Docker**. Instance type: **Free**. Leave everything else as it is.
5. Open **Environment Variables** and add these, using the values from your FalkorDB Cloud page:
   - `FALKORDB_HOST`
   - `FALKORDB_PORT`
   - `FALKORDB_USERNAME`
   - `FALKORDB_PASSWORD`
   - `GEMINI_API_KEY` (optional but recommended: turns on the AI that picks the lookup and words the reply. Leave it out and the question box still works with fixed wording. If you also set `ANTHROPIC_API_KEY`, Claude is used first.)
6. Click **Create Web Service** and wait for "Live" (about 3 to 5 minutes). On the first start it fills the demo shop by itself. If the data is already there it leaves it alone.
7. Copy the address at the top, like `https://bashi-xxxx.onrender.com`.
8. Check it: open `https://bashi-xxxx.onrender.com/health`. You should see `"ok": true` and `"customers": 25`.

## Part 2: keep it alive (the free database stops after 1 idle day and is deleted after 7)

1. On GitHub open the repo, **Settings**, **Secrets and variables**, **Actions**, tab **Variables**.
2. Click **New repository variable**. Name: `BASHI_URL`. Value: the Render address from step 7 (no slash at the end). Save.
3. Open the **Actions** tab, pick **keepalive**, click **Run workflow**. It should go green.
4. It now pings the site every hour. The site checks the database each time, so both stay awake.

Note: Render's free site goes to sleep after 15 minutes without visitors and takes about a minute to wake. Open the link once yourself a few minutes before you record or submit.

## Part 3: if the database ever gets wiped

Restart the Render service (**Manual Deploy**, **Deploy latest commit**). The start-up step sees the empty database and rebuilds the demo shop.

## Run it on your own computer instead

```powershell
pip install -r requirements.txt
python startup.py
```
(On Windows use `python app.py` to start the site, because the production server used on Render does not run on Windows.)

No passwords are stored in any file in the repo. Only the four names above are used.
