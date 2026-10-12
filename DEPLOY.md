# Putting PrepMe Portal online at portal.prepme.education

This is done once and takes about an hour. After that, every change pushed to GitHub
deploys automatically. Expected cost: Render Starter about US$7/month, plus Neon (Free, or
Launch about US$19/month for longer backups).

## 1. Encryption key (do this first, and keep it safe)

```powershell
.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the output in a password manager as **PrepMe FIELD_ENCRYPTION_KEYS**. It encrypts grades,
essays, notes and billing descriptions. **If it is lost, that data can't be recovered.**
Use a different key from the one in your local `.env`.

## 2. Database (Neon)

1. In Neon, create a project named `prepme-portal` in region **AWS US East 1 (N. Virginia)**,
   the same region as the web server.
2. Copy the **pooled** connection string (it ends in `?sslmode=require`).

## 3. Code on GitHub

1. Create a **private** repository named `prepme-portal`.
2. In this folder:
   ```powershell
   git remote add origin https://github.com/<you>/prepme-portal.git
   git push -u origin main
   ```
   `.env`, the local database and the logo PDF are excluded by `.gitignore`.

## 4. Web server (Render)

1. In Render, choose New → Blueprint and select the `prepme-portal` repository. It reads `render.yaml`.
2. Fill in the secret values it asks for:
   - `FIELD_ENCRYPTION_KEYS`: the key from step 1
   - `DATABASE_URL`: the Neon connection string from step 2
   - `COLLEGE_SCORECARD_API_KEY`: your api.data.gov key
   - Email (step 6): `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
3. When the deploy finishes, open the Render **Shell** for the service and create her account:
   ```bash
   python manage.py create_counselor --email her@email.com --first-name Stephanie --last-name Salem
   ```
   At first login she scans the QR code with an authenticator app and saves her backup codes.

## 5. The address portal.prepme.education

1. In Render, go to Settings → Custom Domains and add `portal.prepme.education`.
2. In Squarespace, go to Domains → prepme.education → DNS and add a **CNAME** record: host `portal`,
   value `prepme-portal.onrender.com`. Render issues the HTTPS certificate automatically.
3. Optionally, add a "Student Portal" link in the Squarespace menu pointing to `https://portal.prepme.education`.

## 6. Email for invites and password resets (Resend, free tier)

1. In Resend, add the domain `prepme.education` and add the DNS records it shows in Squarespace.
2. In Render, set: `EMAIL_HOST=smtp.resend.com`, `EMAIL_HOST_USER=resend`,
   `EMAIL_HOST_PASSWORD=<Resend API key>`.

Until email is set up, invites still work: the invite page shows a one-time link she can send by WhatsApp.

## 7. Before real students

- Delete nothing locally; the demo data lives only in your local `db.sqlite3`, never online.
- Have her lawyer review the consent wording (LGPD, minors). Record consents under each student → Consent.
- Data is stored in the U.S. (Render and Neon, Virginia). Mention this in PrepMe's privacy notice.
- In Neon, check that backups / point-in-time restore are on.

## Updating later

Push to GitHub, or ask Claude Code to make a change and push. Render rebuilds and runs migrations automatically.
