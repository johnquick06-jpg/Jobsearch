# Game Job Finder – setup (about 20 minutes, no coding)

Every morning this pulls game-industry jobs, keeps the ones in LA/Orange County or US-remote, scores them against your resume, and updates a simple web page.

## 1. Create a GitHub account and repository
1. Go to github.com and sign up (free).
2. Click **+ → New repository**. Name it `game-job-finder`. Choose **Public** (required for free GitHub Pages) and click **Create repository**.

> Privacy: the repo and page will be public. `config.json` holds your job keywords, not your phone or address. Don't add anything private.

## 2. Upload the files
1. In the new repo click **Add file → Upload files**.
2. Drag in `fetch_jobs.py`, `config.json`, `sample_jobs.json`, `README.md`, and the `docs` folder.
3. Click **Commit changes**.
4. The hidden `.github/workflows/refresh.yml` file is easy to miss. Click **Add file → Create new file**, type the name `.github/workflows/refresh.yml` (typing the slashes makes the folders), paste the file's contents, and commit.

## 3. Get free API keys (optional but strongly recommended)
The studio career boards work with no keys. Keys add Indeed/LinkedIn-style coverage.
- **Adzuna:** developer.adzuna.com → register → copy your *App ID* and *App Key*.
- **JSearch:** rapidapi.com → search "JSearch" → subscribe to the free plan → copy your *X-RapidAPI-Key*.

## 4. Add the keys as Secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add three, with these exact names:
`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RAPIDAPI_KEY`.
(Skip any you don't have.)

## 5. Turn on the live page
Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch `main`, folder `/docs` → **Save**. After a minute your link appears: `https://YOUR-USERNAME.github.io/game-job-finder/`.

## 6. Run it the first time
Repo → **Actions → Refresh jobs → Run workflow**. When the green check appears, reload your page. After this it updates itself every morning at 7am Pacific.

## 7. Check the log and tune
Click the finished run to see which company boards worked (`ok`) or were skipped (`skip`). A skipped board just means the company's board name in `config.json` is wrong or it uses another system. Fix or delete it, and add companies by their board name (the last part of `boards.greenhouse.io/NAME`, `jobs.lever.co/NAME` or `jobs.ashbyhq.com/NAME`).

Edit `config.json` (pencil icon) to change:
- `min_salary` / `near_floor_salary`
- `weights` (how much fit, remote, studio, salary and job type count)
- `target_titles`, `avoid_titles`, `la_oc_places`, and the studio and vendor lists

## Notes
- Salaries come from the listing's pay fields or from ranges written in the description. Hourly rates are converted at 2,080 hours a year. Jobs with no pay show "Unlisted".
- Remote jobs that say they exclude California are hidden.
- Dark Burn is filtered out.
- LinkedIn, Indeed and Glassdoor are covered only through the Adzuna and JSearch aggregators, because those sites forbid scraping.
- The Saved/Applied/Interview tracker is stored in your browser only, so it does not sync between devices.
- To test locally: `python3 fetch_jobs.py --sample`, then `python3 -m http.server -d docs` and open http://localhost:8000.
