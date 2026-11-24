import asyncio, json, os, shutil, subprocess, sys, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ENCORE, CHROME, fixture, restart_mock, plan_screen, takes_screen  # noqa: E402
from playwright.async_api import async_playwright
S = "http://127.0.0.1:8233"; M = "http://127.0.0.1:8771"
root = "/tmp/h3s_v21b"; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
shutil.copytree("/tmp/h3s_v20b/projets", root + "/projets")
cfg = root + "/config.json"; json.dump({"projects_root": root + "/projets", "comfy_url": M, "configured": True, "setup_done": True}, open(cfg, "w"))
srv = subprocess.Popen([sys.executable, "-m", "encore", "--port", "8233", "--no-browser", "--config", cfg], cwd=ENCORE, stdout=subprocess.DEVNULL, stderr=open("/tmp/v21b_srv.log", "w"))
time.sleep(1.5)
FRW = re.compile(r"[éèàùçêâîôû]|\b(prise|prises|branche|aucun|aucune|avec|sans|choisir|annuler|fermer|lancer|générer|réglages|suite|voix|chanson|paroles|dossier|fichier|projet|travail|travaux|attente|cours|groupe|lot|point|modèle|étapes|passe|taille|départ|arrivée|niveaux|nombre|netteté|dépôt|paquet|redémarrez|télécharger|reprendre|suspendre|monter|descendre|retirer|supprimer|renommer|créer|utiliser|parcourir)\b", re.I)
SKIP = re.compile(r"Mais non|Zéro faute|Branche 1|Français|fillette|la_dictee|sortie_ecole|le_plan|s_il_te_plait|la_vitrine|homme|rue")
async def scan(page, label):
    text = await page.evaluate("document.body.innerText")
    titles = await page.evaluate("[...document.querySelectorAll('[title],[placeholder]')].map(e => (e.title||'') + ' ' + (e.placeholder||''))")
    bad = sorted({l.strip() for l in (text.split("\n") + titles) if FRW.search(l) and not SKIP.search(l)})
    print(f"[{label}] {len(bad)}"); [print("   ", l[:160]) for l in bad[:20]]
async def close(page):
    for _ in range(3):
        b = page.locator(".tk-modal .tk-box-head button").last
        if await b.count(): await b.click(); await page.wait_for_timeout(250)
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1500, "height": 950}); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(S + "/"); await page.evaluate("localStorage.setItem('h3studio.project','rue')"); await page.reload(); await page.wait_for_timeout(1500)
        for label in ["Resources…", "Assembled videos…", "Project settings…"]:
            await page.click(f"text={label}"); await page.wait_for_timeout(900); await scan(page, label); await close(page)
        await takes_screen(page); await page.wait_for_timeout(2000)
        await page.evaluate("H3Studio.kit.openUpscale('b1')"); await page.wait_for_timeout(900); await scan(page, "upscale"); await page.screenshot(path="v21_upscale.png"); await close(page)
        await page.click(".tk-brsettings >> nth=0"); await page.wait_for_timeout(1200); await scan(page, "branch settings"); await close(page)
        await page.click(".tk-newbranch"); await page.wait_for_timeout(900); await scan(page, "new branch"); await close(page)
        await page.click("#studioQueueBtn"); await page.wait_for_timeout(900); await scan(page, "queue"); await close(page)
        await page.click("text=Installation…"); await page.wait_for_timeout(1500); await scan(page, "setup"); await page.screenshot(path="v21_setup.png")
        await page.keyboard.press("Escape"); await page.reload(); await page.wait_for_timeout(1200)
        await page.click("text=☰ Projects"); await page.wait_for_timeout(900); await scan(page, "home"); await page.screenshot(path="v21_home.png")
        print("errors", errs[:5])
        await b.close()
asyncio.run(main()); srv.terminate()
