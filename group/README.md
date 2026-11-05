# Stansfeld Research Group website

Static site for GitHub Pages (no build step).

- One HTML file per page; shared styles in `style.css`.
- To add a person, copy an `<article class="person">` block in `members.html` (or `<article class="alum">` in `alumni.html`).
- Papers update themselves: every Monday a GitHub Action (`.github/workflows/update-publications.yml`) rebuilds the list in `publications.html` from PubMed (`Stansfeld PJ[au]`). Don't edit between the `PUBS:START`/`PUBS:END` markers by hand. To refresh now, open the repo's **Actions** tab → **Update publications** → **Run workflow**.
- The menu is repeated at the top of each page; edit all files if you add a page.

Images live in `images/` (copied from the WordPress media export, resized for the web). The Complexes page's structure images are still loaded from testing55952.wordpress.com.
