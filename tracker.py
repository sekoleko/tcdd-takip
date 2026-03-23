import os
import json
import time
import threading
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = ""
TELEGRAM_CHAT  = ""

def telegram_gonder(mesaj, token=None, chat=None):
    t = token or TELEGRAM_TOKEN
    c = chat  or TELEGRAM_CHAT
    if not t or not c:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{t}/sendMessage",
            json={"chat_id": c, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.error(f"Telegram hatası: {e}")

def headless_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    import subprocess
    # Sistemdeki chromium/chrome yolunu bul
    for chrome_path in [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser", 
        "/usr/bin/google-chrome",
        "/nix/var/nix/profiles/default/bin/chromium",
        "/run/current-system/sw/bin/chromium",
    ]:
        if os.path.exists(chrome_path):
            opts.binary_location = chrome_path
            break

    # Sistemdeki chromedriver yolunu bul
    for driver_path in [
        "/usr/bin/chromedriver",
        "/nix/var/nix/profiles/default/bin/chromedriver",
        "/run/current-system/sw/bin/chromedriver",
    ]:
        if os.path.exists(driver_path):
            driver = webdriver.Chrome(
                service=Service(driver_path),
                options=opts
            )
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return driver

    # Hiçbiri bulunamazsa webdriver-manager dene
    from webdriver_manager.chrome import ChromeDriverManager
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver

def taze_veri_al(driver):
    for entry in reversed(driver.get_log("performance")):
        try:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") == "Network.responseReceived":
                if "train-availability" in msg["params"]["response"]["url"]:
                    body = driver.execute_cdp_cmd(
                        "Network.getResponseBody",
                        {"requestId": msg["params"]["requestId"]}
                    )
                    return json.loads(body["body"])
        except:
            continue
    return None

def trainleri_cek(data):
    out = []
    for leg in data.get("trainLegs", []):
        for av in leg.get("trainAvailabilities", []):
            for t in av.get("trains", []):
                out.append(t)
    return out

def ekonomi_kontrol(data, utc_saatler):
    res = []
    for t in trainleri_cek(data):
        segs = t.get("trainSegments", [])
        if not segs:
            continue
        try:
            sutc = segs[0]["departureTime"].split("T")[1][:5]
        except:
            continue
        if sutc not in utc_saatler:
            continue
        bos = 0
        for fare in t.get("availableFareInfo", []):
            for cc in fare.get("cabinClasses", []):
                if "EKONOM" in cc.get("cabinClass", {}).get("name", "").upper():
                    bos = cc.get("availabilityCount", 0)
        tren_adi = t.get("name", "?")
        res.append({"saat_utc": sutc, "tren": tren_adi, "bos": bos})
    return res

def utc_to_tr(s):
    h, m = map(int, s.split(":"))
    return f"{(h+3)%24:02d}:{m:02d}"

def sefer_ara_headless(kalkis, varis, tarih):
    """Headless Chrome ile TCDD'den sefer listesi çek."""
    driver = None
    try:
        driver = headless_driver()
        driver.get("https://ebilet.tcddtasimacilik.gov.tr/")
        wait = WebDriverWait(driver, 20)
        time.sleep(3)

        # Kalkış
        kalkis_input = wait.until(EC.element_to_be_clickable((By.ID, "fromTrainInput")))
        kalkis_input.click()
        kalkis_input.clear()
        kalkis_input.send_keys(kalkis)
        time.sleep(2)
        try:
            items = driver.find_elements(By.CSS_SELECTOR, "ul.dropdown-menu li, .dropdown-item")
            for item in items:
                if kalkis.lower()[:4] in item.text.lower() and item.is_displayed():
                    item.click()
                    break
        except:
            kalkis_input.send_keys(Keys.RETURN)
        time.sleep(1.5)

        # Varış
        varis_input = wait.until(EC.element_to_be_clickable((By.ID, "toTrainInput")))
        varis_input.click()
        varis_input.clear()
        varis_input.send_keys(varis)
        time.sleep(2)
        try:
            items = driver.find_elements(By.CSS_SELECTOR, "ul.dropdown-menu li, .dropdown-item")
            for item in items:
                if varis.lower()[:4] in item.text.lower() and item.is_displayed():
                    item.click()
                    break
        except:
            varis_input.send_keys(Keys.RETURN)
        time.sleep(1.5)

        # Tarih
        try:
            gun, ay, yil = tarih.split("-")
            gun_int = int(gun)
            ay_int  = int(ay)
            ay_adlari = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
                         "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
            hedef_ay = ay_adlari[ay_int - 1]

            tarih_el = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR,
                 ".multipleDateRangePickerStart, "
                 ".customMultipleDateRangePicker input, "
                 ".vue-daterange-picker input")
            ))
            tarih_el.click()
            time.sleep(1.5)

            for _ in range(24):
                try:
                    baslik = driver.find_element(
                        By.CSS_SELECTOR,
                        ".drp-calendar.left .calendar-table thead tr th.month"
                    ).text
                    if hedef_ay in baslik and str(yil) in baslik:
                        break
                    ileri = driver.find_element(
                        By.CSS_SELECTOR,
                        ".drp-calendar.left thead tr th.next"
                    )
                    ileri.click()
                    time.sleep(0.4)
                except:
                    break

            time.sleep(0.5)
            gunler = driver.find_elements(
                By.CSS_SELECTOR,
                ".drp-calendar.left .calendar-table tbody td:not(.off):not(.disabled)"
            )
            for g in gunler:
                if g.text.strip() == str(gun_int):
                    g.click()
                    break
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Tarih seçilemedi: {e}")

        # Sefer Ara
        try:
            ara_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[contains(text(),'Ara') or contains(@class,'searchButton')]")
            ))
            ara_btn.click()
        except:
            varis_input.send_keys(Keys.RETURN)
        time.sleep(6)

        data = taze_veri_al(driver)
        if not data:
            return None, "Veri alınamadı"

        seferler = []
        for t in trainleri_cek(data):
            segs = t.get("trainSegments", [])
            if not segs:
                continue
            try:
                sutc = segs[0]["departureTime"].split("T")[1][:5]
                str_ = utc_to_tr(sutc)
            except:
                continue
            seferler.append({
                "saat_tr":  str_,
                "saat_utc": sutc,
                "tren":     t.get("name", "?"),
                "bos":      None
            })

        return seferler, None

    except Exception as e:
        logger.error(f"sefer_ara_headless hatası: {e}")
        return None, str(e)
    finally:
        if driver:
            driver.quit()


class TakipMotoru:
    def __init__(self):
        self.takip_listesi = []
        self.calisiyor     = False
        self.thread        = None
        self.loglar        = []
        self.kontrol_no    = 0
        self.bulunan       = 0
        self.tg_token      = ""
        self.tg_chat       = ""

    def log(self, msg, tip="info"):
        entry = {
            "zaman": datetime.now().strftime("%H:%M:%S"),
            "msg":   msg,
            "tip":   tip
        }
        self.loglar.append(entry)
        if len(self.loglar) > 200:
            self.loglar.pop(0)
        logger.info(msg)

    def sefer_ekle(self, kalkis, varis, tarih, saatler_tr, saatler_utc):
        self.takip_listesi.append({
            "id":          len(self.takip_listesi) + 1,
            "kalkis":      kalkis,
            "varis":       varis,
            "tarih":       tarih,
            "saatler_tr":  saatler_tr,
            "saatler_utc": saatler_utc,
            "durum":       "bekliyor",
            "durum_detay": "Kontrol bekleniyor...",
            "son_data":    None,
            "driver":      None,
        })

    def sefer_sil(self, idx):
        if 0 <= idx < len(self.takip_listesi):
            s = self.takip_listesi.pop(idx)
            if s.get("driver"):
                try:
                    s["driver"].quit()
                except:
                    pass

    def baslat(self, aralik=30):
        if self.calisiyor:
            return
        self.calisiyor = True
        self.kontrol_no = 0
        self.bulunan = 0

        # Her sefer için driver aç
        for s in self.takip_listesi:
            if not s.get("driver"):
                try:
                    s["driver"] = headless_driver()
                    s["driver"].get("https://ebilet.tcddtasimacilik.gov.tr/")
                    time.sleep(2)
                except Exception as e:
                    self.log(f"Driver açılamadı: {e}", "err")

        self.thread = threading.Thread(
            target=self._dongu, args=(aralik,), daemon=True
        )
        self.thread.start()
        self.log("Takip başlatıldı!", "ok")

        ozet = "🚆 <b>TCDD Web Takip başladı!</b>\n\n"
        for s in self.takip_listesi:
            ozet += f"🚉 {s['kalkis']} → {s['varis']} | {', '.join(s['saatler_tr'])}\n"
        telegram_gonder(ozet, self.tg_token, self.tg_chat)

    def durdur(self):
        self.calisiyor = False
        self.log(f"Durduruldu. Kontrol: {self.kontrol_no} | Uyarı: {self.bulunan}", "warn")
        telegram_gonder(
            f"⏹ Durduruldu.\nKontrol: {self.kontrol_no} | Uyarı: {self.bulunan}",
            self.tg_token, self.tg_chat
        )

    def _dongu(self, aralik):
        while self.calisiyor:
            self.kontrol_no += 1
            self.log(f"=== Kontrol #{self.kontrol_no} ===", "info")

            for s in self.takip_listesi:
                if not self.calisiyor:
                    break
                self.log(f"{s['kalkis']} → {s['varis']} kontrol ediliyor...", "info")

                try:
                    if not s.get("driver"):
                        s["driver"] = headless_driver()
                        s["driver"].get("https://ebilet.tcddtasimacilik.gov.tr/")
                        time.sleep(2)

                    s["driver"].refresh()
                    time.sleep(6)
                    data = taze_veri_al(s["driver"])
                    if data:
                        s["son_data"] = data
                    else:
                        data = s["son_data"]
                except Exception as e:
                    self.log(f"Driver hatası: {e}", "err")
                    data = s.get("son_data")

                if not data:
                    self.log("Veri yok", "warn")
                    continue

                detaylar = []
                for r in ekonomi_kontrol(data, s["saatler_utc"]):
                    str_ = utc_to_tr(r["saat_utc"])
                    if r["bos"] == 0:
                        self.log(f"  {str_} → DOLU", "muted")
                        detaylar.append(f"{str_}: DOLU")
                        s["durum"] = "DOLU"
                    else:
                        self.bulunan += 1
                        self.log(f"  ✅ {str_} → {r['bos']} BOŞ KOLTUK!", "ok")
                        detaylar.append(f"{str_}: {r['bos']} BOŞ")
                        s["durum"] = "BOS"

                        mesaj = (
                            f"🚆 <b>BİLET AÇILDI!</b>\n\n"
                            f"🚉 {s['kalkis']} → {s['varis']}\n"
                            f"📅 {s['tarih']}\n"
                            f"⏰ {str_}\n"
                            f"💺 Ekonomi: <b>{r['bos']} boş koltuk</b>\n\n"
                            f"👉 https://ebilet.tcddtasimacilik.gov.tr"
                        )
                        telegram_gonder(mesaj, self.tg_token, self.tg_chat)

                s["durum_detay"] = " | ".join(detaylar) if detaylar else "Kontrol edildi"

            time.sleep(aralik)

    def durum_json(self):
        return {
            "calisiyor":  self.calisiyor,
            "kontrol_no": self.kontrol_no,
            "bulunan":    self.bulunan,
            "takip":      [
                {
                    "id":          s["id"],
                    "kalkis":      s["kalkis"],
                    "varis":       s["varis"],
                    "tarih":       s["tarih"],
                    "saatler_tr":  s["saatler_tr"],
                    "durum":       s["durum"],
                    "durum_detay": s["durum_detay"],
                }
                for s in self.takip_listesi
            ],
            "loglar": self.loglar[-50:],
        }


motor = TakipMotoru()
