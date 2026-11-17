import re
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


BRISIM_URL = "https://brisim.bri.co.id/"
PROFILE_DIR = Path(__file__).resolve().parent / "data" / "browser_profile"
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "TL506"
BRANCH_FILE = Path(__file__).resolve().with_name("Branch.md")

ID_KANWIL = "rv_inst_ctl08_ctl03"
ID_CABANG = "rv_inst_ctl08_ctl05"
ID_UNIT_KERJA = "rv_inst_ctl08_ctl07"
ID_TANGGAL = "rv_inst_ctl08_ctl09_ddValue"
ID_VIEW_REPORT = "rv_inst_ctl08_ctl00"
ID_EXPORT_MENU = "rv_inst_ctl09_ctl04_ctl00_ButtonLink"

PENGECUALIAN_KANWIL = (
    "CABANG LUAR NEGERI",
    "KANTOR CABANG TAIWAN",
    "KC LUAR NEGERI",
    "CABANG LUAR NEGERI",
    "KAS KANPUS",
    "KAS KANPUS",
    "KANINS",
    "DIKLAT",
)


class TL506Downloader:
    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None
        self._parameter_frames = {}

    @staticmethod
    def baca_branch_md(path):
        lines = [
            line.strip()
            for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        if len(lines) < 2:
            raise ValueError(
                f"{path} harus berisi tanggal di baris pertama "
                "dan minimal satu kode branch."
            )

        try:
            tanggal = date.fromisoformat(lines[0]).isoformat()
        except ValueError as error:
            raise ValueError(
                f"Tanggal di {path} tidak valid: {lines[0]!r}"
            ) from error

        branch_codes = lines[1:]
        invalid = [
            code for code in branch_codes
            if not re.fullmatch(r"\d{1,5}", code)
        ]
        if invalid:
            raise ValueError(
                f"Kode branch harus berupa angka 1-5 digit: {invalid}"
            )
        if len(set(branch_codes)) != len(branch_codes):
            raise ValueError(f"Terdapat kode branch duplikat di {path}.")
        return tanggal, branch_codes

    def buka(self, status_callback=None):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            accept_downloads=True,
        )
        self.page = (
            self.context.pages[0]
            if self.context.pages
            else self.context.new_page()
        )
        if status_callback:
            status_callback("Membuka BRISIM...")
        self.page.goto(
            BRISIM_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        if self._sesi_login_aktif():
            print("[BERHASIL] Sesi BRISIM tersimpan masih aktif.")
        else:
            print(
                "[INFO] Silakan login BRISIM dan selesaikan OTP "
                "secara manual di browser."
            )
            if status_callback:
                status_callback(
                    "Silakan login BRISIM dan selesaikan OTP pada jendela "
                    "browser yang terbuka."
                )
            self._klik_login()
            if not self._tunggu_login_manual():
                raise RuntimeError(
                    "Login BRISIM belum terdeteksi setelah 5 menit."
                )

        self._tangani_pemberitahuan(status_callback=status_callback)
        self._sinkronkan_halaman_aktif()
        if status_callback:
            status_callback("Login BRISIM terdeteksi; menyiapkan laporan TL506.")

    def _sinkronkan_halaman_aktif(self):
        if not self.context:
            return
        for page in reversed(self.context.pages):
            try:
                if page.is_closed():
                    continue
                if self._halaman_sudah_login(page):
                    self.page = page
                    return
            except Exception:
                continue
        for page in reversed(self.context.pages):
            if not page.is_closed():
                self.page = page
                return

    @staticmethod
    def _halaman_sudah_login(page):
        try:
            if "brisim.bri.co.id" not in page.url:
                return False
            if page.get_by_text(
                "Log In with BRILian ID",
                exact=True,
            ).first.is_visible():
                return False
            return (
                page.get_by_text("Customers", exact=True).count() > 0
                or page.get_by_text(
                    "Selamat datang di New BRISIM!",
                    exact=False,
                ).count() > 0
            )
        except Exception:
            return False

    def _klik_login(self):
        pola = re.compile(r"Log In with BRILian ID", re.I)
        for locator in (
            self.page.get_by_role("button", name=pola),
            self.page.get_by_role("link", name=pola),
            self.page.get_by_text("Log In with BRILian ID", exact=True),
        ):
            try:
                if locator.count() and locator.first.is_visible():
                    locator.first.click(timeout=10000)
                    return
            except PlaywrightTimeoutError:
                continue
        raise RuntimeError("Tombol Log In with BRILian ID tidak ditemukan.")

    def _sesi_login_aktif(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self._sinkronkan_halaman_aktif()
            if self._halaman_sudah_login(self.page):
                return True
            self.page.wait_for_timeout(300)
        return False

    def _tunggu_login_manual(self, timeout_ms=300000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self._sinkronkan_halaman_aktif()
            if self._halaman_sudah_login(self.page):
                return True
            self.page.wait_for_timeout(500)
        return False

    def _pemberitahuan_terlihat(self):
        if not self.context:
            return False
        for page in reversed(self.context.pages):
            try:
                if page.is_closed():
                    continue
                for frame in reversed(page.frames):
                    notice = frame.get_by_text(
                        "Selamat datang di New BRISIM!",
                        exact=False,
                    )
                    if any(
                        notice.nth(index).is_visible()
                        for index in range(notice.count())
                    ):
                        return True
            except PlaywrightError:
                continue
        return False

    def _tangani_pemberitahuan(
        self,
        status_callback=None,
        timeout_ms=15000,
    ):
        deadline = time.monotonic() + timeout_ms / 1000
        notice_seen = False
        status_reported = False

        while time.monotonic() < deadline:
            notice_visible = False
            for page in reversed(self.context.pages):
                try:
                    if page.is_closed():
                        continue
                    for frame in reversed(page.frames):
                        notice = frame.get_by_text(
                            "Selamat datang di New BRISIM!",
                            exact=False,
                        )
                        if not any(
                            notice.nth(index).is_visible()
                            for index in range(notice.count())
                        ):
                            continue

                        notice_seen = True
                        notice_visible = True
                        self.page = page
                        if status_callback and not status_reported:
                            status_callback(
                                "Menutup pemberitahuan BRISIM dengan "
                                "menekan Setuju..."
                            )
                            status_reported = True

                        button_locators = (
                            frame.get_by_role(
                                "button",
                                name=re.compile(r"^\s*Setuju\s*$", re.I),
                            ),
                            frame.locator(
                                "input[type='button'][value='Setuju'], "
                                "input[type='submit'][value='Setuju']"
                            ),
                            frame.get_by_text("Setuju", exact=True),
                        )
                        for buttons in button_locators:
                            for index in range(buttons.count()):
                                button = buttons.nth(index)
                                try:
                                    if (
                                        not button.is_visible()
                                        or not button.is_enabled()
                                    ):
                                        continue
                                    button.click(timeout=5000)
                                except PlaywrightTimeoutError:
                                    continue

                                dismiss_deadline = min(
                                    deadline,
                                    time.monotonic() + 5000 / 1000,
                                )
                                while time.monotonic() < dismiss_deadline:
                                    if not self._pemberitahuan_terlihat():
                                        print(
                                            "[BERHASIL] Pemberitahuan BRISIM "
                                            "ditutup."
                                        )
                                        return True
                                    self.page.wait_for_timeout(200)
                                break
                except PlaywrightError:
                    continue

            if notice_seen and not notice_visible:
                return True
            self.page.wait_for_timeout(250)

        if notice_seen:
            raise RuntimeError(
                "Pemberitahuan BRISIM tampil, tetapi tombol Setuju tidak "
                "berhasil ditekan atau dialog tidak tertutup."
            )
        return False

    def _klik_menu(self, text, timeout_ms=15000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self._sinkronkan_halaman_aktif()
            locator = self.page.get_by_text(text, exact=True)
            for index in range(locator.count()):
                item = locator.nth(index)
                try:
                    if item.is_visible():
                        item.click(timeout=10000)
                        self.page.wait_for_timeout(700)
                        return True
                except PlaywrightTimeoutError:
                    continue
            self.page.wait_for_timeout(300)
        return False

    def _locator_aktif(self, selector, description, timeout_ms=30000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            for page in reversed(self.context.pages):
                try:
                    if page.is_closed():
                        continue
                    for frame in reversed(page.frames):
                        locator = frame.locator(selector)
                        for index in range(locator.count()):
                            candidate = locator.nth(index)
                            if candidate.is_visible() and candidate.is_enabled():
                                self.page = page
                                return frame, candidate
                except Exception:
                    continue
            self.page.wait_for_timeout(250)
        raise RuntimeError(
            f"Kontrol {description} tidak terlihat atau belum aktif "
            f"(selector {selector})."
        )

    @staticmethod
    def _normalisasi_label(value):
        value = (value or "").replace("\xa0", " ")
        return re.sub(r"\s+", " ", value).strip().upper()

    @staticmethod
    def _normalisasi_kode(value):
        digits = str(value).strip()
        if not re.fullmatch(r"\d{1,5}", digits):
            raise ValueError(f"Kode unit kerja tidak valid: {value!r}")
        return digits.zfill(5)

    def _ambil_item_pilihan(self, parameter_id):
        prefix = f"{parameter_id}_divDropDown_"
        label_selector = f"label[for^='{prefix}']"
        preferred = self._parameter_frames.get(parameter_id)
        candidates = []

        for page in reversed(self.context.pages):
            try:
                if page.is_closed():
                    continue
                for frame in reversed(page.frames):
                    labels = frame.locator(label_selector)
                    count = labels.count()
                    if not count:
                        continue
                    visible_count = sum(
                        labels.nth(index).is_visible()
                        for index in range(count)
                    )
                    candidates.append(
                        (
                            visible_count,
                            frame is preferred,
                            page,
                            frame,
                            labels,
                            count,
                        )
                    )
            except Exception:
                continue

        if not candidates:
            return []

        _, _, page, frame, labels, count = max(
            candidates,
            key=lambda item: (item[0], item[1]),
        )
        self.page = page
        self._parameter_frames[parameter_id] = frame
        items = {}

        for index in range(count):
            label = labels.nth(index)
            checkbox_id = label.get_attribute("for")
            if not checkbox_id:
                continue
            checkbox_locator = frame.locator(
                "input[type='checkbox']"
                f"[id='{checkbox_id}']"
            )
            if not checkbox_locator.count():
                continue

            select_all = checkbox_id.endswith("_ctl00")
            handler = "OnSelectAllClick" if select_all else "OnValidValueClick"
            checkbox = checkbox_locator.first
            for checkbox_index in range(checkbox_locator.count()):
                option = checkbox_locator.nth(checkbox_index)
                if handler in (option.get_attribute("onclick") or ""):
                    checkbox = option
                    break

            item = {
                "id": checkbox_id,
                "checkbox": checkbox,
                "label_locator": label,
                "label": (label.text_content() or "").strip(),
                "is_select_all": select_all,
                "onclick": checkbox.get_attribute("onclick") or "",
            }
            current = items.get(checkbox_id)
            if current is None or (
                handler not in current["onclick"]
                and handler in item["onclick"]
            ):
                items[checkbox_id] = item
        return list(items.values())

    def _buka_pilihan(self, parameter_id):
        selector = (
            f"#{parameter_id}_txtValue"
            if parameter_id == ID_CABANG
            else f"#{parameter_id}_ctl01"
        )
        frame, trigger = self._locator_aktif(
            selector,
            f"dropdown {parameter_id}",
        )
        self._parameter_frames[parameter_id] = frame
        trigger.click()

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if parameter_id == ID_CABANG:
                item = self._ambil_select_all(parameter_id)
                if item and item["label_locator"].is_visible():
                    return [item]
                self.page.wait_for_timeout(200)
                continue

            items = self._ambil_item_pilihan(parameter_id)
            if any(
                item["label_locator"].is_visible()
                for item in items
            ):
                return items
            self.page.wait_for_timeout(250)
        raise RuntimeError(
            f"Pilihan parameter {parameter_id} tidak muncul setelah diklik."
        )

    def _ambil_select_all(self, parameter_id):
        checkbox_id = f"{parameter_id}_divDropDown_ctl00"
        label_selector = f"label[for='{checkbox_id}']"
        checkbox_selector = (
            "input[type='checkbox']"
            f"[id='{checkbox_id}']"
        )

        for page in reversed(self.context.pages):
            try:
                if page.is_closed():
                    continue
                for frame in reversed(page.frames):
                    labels = frame.locator(label_selector)
                    checkboxes = frame.locator(checkbox_selector)
                    if not labels.count() or not checkboxes.count():
                        continue

                    label = labels.first
                    for index in range(labels.count()):
                        candidate = labels.nth(index)
                        if candidate.is_visible():
                            label = candidate
                            break

                    checkbox = checkboxes.first
                    for index in range(checkboxes.count()):
                        candidate = checkboxes.nth(index)
                        if "OnSelectAllClick" in (
                            candidate.get_attribute("onclick") or ""
                        ):
                            checkbox = candidate
                            break

                    self.page = page
                    self._parameter_frames[parameter_id] = frame
                    return {
                        "id": checkbox_id,
                        "checkbox": checkbox,
                        "label_locator": label,
                        "label": (label.text_content() or "").strip(),
                        "is_select_all": True,
                        "onclick": checkbox.get_attribute("onclick") or "",
                    }
            except Exception:
                continue
        return None

    @staticmethod
    def _ubah_checkbox(item, checked):
        checkbox = item["checkbox"]
        if checkbox.is_checked() == checked:
            return
        if not item["onclick"]:
            raise RuntimeError(
                f"Handler checkbox {item['label']!r} tidak ditemukan."
            )
        checkbox.evaluate("(element) => element.click()")
        if checkbox.is_checked() != checked:
            raise RuntimeError(
                f"Status pilihan {item['label']!r} tidak berubah."
            )

    def _pilih_semua(self, parameter_id, pengecualian=()):
        items = self._buka_pilihan(parameter_id)
        select_all = next(
            (item for item in items if item["is_select_all"]),
            None,
        )
        if select_all is None:
            raise RuntimeError(
                f"Checkbox (Select All) tidak ditemukan untuk {parameter_id}."
            )

        checkbox = select_all["checkbox"]
        if not checkbox.is_checked():
            checkbox.evaluate("(element) => element.click()")
        elif "OnSelectAllClick" in select_all["onclick"]:
            checkbox.evaluate(
                "(element) => element.onclick.call(element)"
            )
        else:
            raise RuntimeError(
                f"Handler OnSelectAllClick tidak ditemukan untuk {parameter_id}."
            )

        if parameter_id == ID_CABANG:
            print("[INFO] Menerapkan pilihan semua Cabang...")
            self.page.wait_for_timeout(500)
            self._tutup_pilihan(parameter_id)
            self.page.wait_for_timeout(500)
            if not self._tunggu_loading_selesai():
                raise TimeoutError(
                    "BRISIM belum selesai menerapkan pilihan semua Cabang."
                )
            print("[BERHASIL] Pilihan semua Cabang sudah diterapkan.")
            return

        self.page.wait_for_timeout(750)

        excluded = tuple(
            self._normalisasi_label(label)
            for label in pengecualian
        )
        found = set()
        for item in self._ambil_item_pilihan(parameter_id):
            if item["is_select_all"]:
                continue
            label = self._normalisasi_label(item["label"])
            matches = [name for name in excluded if name in label]
            if matches:
                self._ubah_checkbox(item, False)
                found.update(matches)

        missing = set(excluded) - found
        if missing:
            raise RuntimeError(
                "Pilihan Kanwil yang harus dikecualikan tidak ditemukan: "
                + ", ".join(sorted(missing))
            )
        self._tutup_pilihan(parameter_id)

    def _tutup_pilihan(self, parameter_id):
        if parameter_id == ID_CABANG:
            selector = f"label[for='{parameter_id}_txtValue']"
            frame = self._parameter_frames.get(parameter_id)
            label = frame.locator(selector) if frame else None
            if label is None or not label.count() or not label.first.is_visible():
                frame, label = self._frame_locator_aktif(
                    selector,
                    "label Cabang untuk menerapkan pilihan",
                )
                self._parameter_frames[parameter_id] = frame
            label.first.click()

            label_selector = (
                "label[for='"
                f"{parameter_id}_divDropDown_ctl00']"
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                applied = True
                for page in reversed(self.context.pages):
                    try:
                        if page.is_closed():
                            continue
                        for frame in reversed(page.frames):
                            labels = frame.locator(label_selector)
                            if any(
                                labels.nth(index).is_visible()
                                for index in range(labels.count())
                            ):
                                applied = False
                                break
                        if not applied:
                            break
                    except Exception:
                        continue
                if applied:
                    return
                self.page.wait_for_timeout(250)
            raise TimeoutError(
                "Picker Cabang tidak tertutup setelah pilihan diterapkan."
            )

        _, trigger = self._locator_aktif(
            f"#{parameter_id}_ctl01",
            f"dropdown {parameter_id}",
        )
        trigger.click()

    def _tunggu_loading_selesai(self, timeout_ms=120000):
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        selectors = (
            ".dataTables_processing, .spinner-border, .spinner, .loader, "
            "#loading, .swal2-loading, .blockUI"
        )
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            loading = False
            for page in self.context.pages:
                try:
                    for frame in page.frames:
                        locators = frame.locator(selectors)
                        for index in range(locators.count()):
                            if locators.nth(index).is_visible():
                                loading = True
                                break
                        if loading:
                            break
                except Exception:
                    continue
                if loading:
                    break
            if not loading:
                return True
            self.page.wait_for_timeout(500)
        return False

    def _pilih_tanggal(self, tanggal):
        _, selector = self._locator_aktif(
            f"#{ID_TANGGAL}",
            "parameter tanggal",
        )
        try:
            selector.select_option(label=tanggal)
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                f"Tanggal {tanggal} tidak tersedia di form TL506."
            ) from error

    def _pilih_unit_kerja(self, branch_code):
        selector = f"#{ID_UNIT_KERJA}_ctl01"
        frame, trigger = self._locator_aktif(
            selector,
            "dropdown Unit Kerja",
        )
        self._parameter_frames[ID_UNIT_KERJA] = frame
        trigger.click()

        target = self._normalisasi_kode(branch_code)
        prefix = f"{ID_UNIT_KERJA}_divDropDown_"
        label_selector = f"label[for^='{prefix}']"
        deadline = time.monotonic() + 30
        chosen_label = None
        chosen_id = None

        while time.monotonic() < deadline:
            for page in reversed(self.context.pages):
                try:
                    if page.is_closed():
                        continue
                    for candidate_frame in reversed(page.frames):
                        labels = candidate_frame.locator(label_selector)
                        matches = labels.evaluate_all(
                            """(elements, targetCode) => elements
                                .map(label => ({
                                    label,
                                    id: label.htmlFor,
                                    text: (label.textContent || '')
                                        .replace(/\\u00a0/g, ' ')
                                        .trim()
                                }))
                                .filter(item => {
                                    const match = item.text.match(/^([0-9]+)\\s*--/);
                                    return match && match[1].padStart(5, '0') === targetCode;
                                })
                                .map(item => ({
                                    id: item.id,
                                    visible: item.label.getClientRects().length > 0
                                }))""",
                            target,
                        )
                        visible_match = next(
                            (item for item in matches if item["visible"]),
                            None,
                        )
                        if visible_match:
                            self.page = page
                            frame = candidate_frame
                            chosen_id = visible_match["id"]
                            label_candidates = frame.locator(
                                f"label[for='{chosen_id}']"
                            )
                            for label_index in range(
                                label_candidates.count()
                            ):
                                candidate_label = label_candidates.nth(
                                    label_index
                                )
                                if candidate_label.is_visible():
                                    chosen_label = candidate_label
                                    break
                            self._parameter_frames[ID_UNIT_KERJA] = frame
                            break
                    if chosen_id:
                        break
                except Exception:
                    continue
            if chosen_id:
                break
            self.page.wait_for_timeout(250)

        if not chosen_id or chosen_label is None:
            print(
                f"[LEWATI] Unit Kerja {target} tidak ditemukan pada daftar."
            )
            self._tutup_pilihan(ID_UNIT_KERJA)
            return False

        checkbox_selector = (
            "input[type='checkbox']"
            f"[id='{chosen_id}']"
            "[onclick*='OnValidValueClick']"
        )
        checkbox = frame.locator(checkbox_selector)
        if not checkbox.count():
            raise RuntimeError(
                f"Checkbox untuk Unit Kerja {target} tidak ditemukan."
            )

        target_checkbox = checkbox.first
        checked_selector = (
            "input[type='checkbox']"
            f"[id^='{prefix}']"
            "[onclick*='OnValidValueClick']:checked"
        )
        previously_checked_ids = frame.locator(
            checked_selector
        ).evaluate_all(
            "(elements) => [...new Set(elements.map(element => element.id))]"
        )
        for checked_id in previously_checked_ids:
            if checked_id == chosen_id:
                continue
            previous = frame.locator(
                "input[type='checkbox']"
                f"[id='{checked_id}']"
                "[onclick*='OnValidValueClick']:checked"
            )
            attempts = 0
            while previous.count() and attempts < 3:
                previous.first.evaluate("(element) => element.click()")
                attempts += 1
                self.page.wait_for_timeout(100)
                previous = frame.locator(
                    "input[type='checkbox']"
                    f"[id='{checked_id}']"
                    "[onclick*='OnValidValueClick']:checked"
                )
            if previous.count():
                raise RuntimeError(
                    f"Unit Kerja sebelumnya {checked_id} tidak bisa "
                    "dilepas pilihannya."
                )

        if not target_checkbox.is_checked():
            chosen_label.evaluate("(element) => element.click()")
            check_deadline = time.monotonic() + 3
            while (
                time.monotonic() < check_deadline
                and not target_checkbox.is_checked()
            ):
                self.page.wait_for_timeout(100)

        if not target_checkbox.is_checked():
            target_checkbox.evaluate("(element) => element.click()")
            self.page.wait_for_timeout(300)

        if not target_checkbox.is_checked():
            handler = target_checkbox.get_attribute("onclick") or ""
            raise RuntimeError(
                f"Unit Kerja {target} belum tercentang setelah memilih "
                f"label {chosen_label.inner_text().strip()!r}. "
                f"Handler checkbox: {handler!r}"
            )

        print(f"[BERHASIL] Unit Kerja {target} sudah tercentang.")
        self._tutup_pilihan(ID_UNIT_KERJA)
        return True

    def _unduh_excel(self, tanggal, branch_code, output_dir=OUTPUT_DIR):
        if not self._tunggu_loading_selesai():
            raise TimeoutError(
                f"BRISIM masih loading setelah memilih Unit Kerja "
                f"{self._normalisasi_kode(branch_code)}."
            )
        _, view_report = self._locator_aktif(
            f"#{ID_VIEW_REPORT}",
            "View Report",
        )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / f"TL506_{tanggal}_{branch_code}.xlsx"
        if target_path.exists():
            raise FileExistsError(
                f"File sudah ada dan tidak akan ditimpa: {target_path}"
            )

        with self.page.expect_download(timeout=180000) as download_info:
            view_report.click(timeout=30000)
            if not self._tunggu_loading_selesai():
                raise TimeoutError(
                    f"Report branch {branch_code} masih loading."
                )
            _, export = self._locator_aktif(
                f"#{ID_EXPORT_MENU}",
                "menu Export",
                timeout_ms=120000,
            )
            export.click()
            _, excel = self._locator_aktif(
                "a.ActiveLink[title='Excel']",
                "opsi Excel",
            )
            excel.click()

        download_info.value.save_as(target_path)
        print(f"[BERHASIL] {target_path}")

    def proses(
        self,
        tanggal,
        branch_codes,
        output_dir=OUTPUT_DIR,
        progress_callback=None,
        status_callback=None,
    ):
        if status_callback:
            status_callback("Membuka menu laporan TL506...")
        if not self._klik_menu("Favorite Menu"):
            raise RuntimeError("Menu Favorite Menu tidak ditemukan.")
        self.page.wait_for_timeout(500)
        title = "TL506 - Report Transaction Listing By Teller ID [1 Row]"
        link = self.page.locator(
            f'a.fav_menu_link[title="{title}"]'
        )
        if not link.count():
            link = self.page.locator("a.fav_menu_link").filter(
                has_text=re.compile(
                    r"TL506\s*-\s*Report Transaction Listing",
                    re.I,
                )
            )
        link.first.wait_for(state="visible", timeout=15000)
        link.first.click(timeout=15000)
        self._locator_aktif(f"#{ID_KANWIL}_ctl01", "dropdown Kanwil")

        self._pilih_semua(
            ID_KANWIL,
            pengecualian=PENGECUALIAN_KANWIL,
        )
        print("[INFO] Menunggu BRISIM selesai memuat Kanwil...")
        if not self._tunggu_loading_selesai():
            raise TimeoutError(
                "BRISIM masih loading setelah Kanwil dipilih; "
                "dropdown Cabang belum dibuka."
            )
        self._locator_aktif(
            f"#{ID_CABANG}_txtValue",
            "form Cabang setelah Kanwil dimuat",
        )
        self._pilih_semua(ID_CABANG)
        print(f"[INFO] Memilih tanggal laporan {tanggal} dari Branch.md...")
        self._pilih_tanggal(tanggal)

        berhasil = 0
        dilewati = []
        total = len(branch_codes)
        for index, branch_code in enumerate(branch_codes, start=1):
            normalized_code = self._normalisasi_kode(branch_code)
            if status_callback:
                status_callback(
                    f"Memproses branch {index}/{total}: {normalized_code}"
                )
            if progress_callback:
                progress_callback(
                    index - 1,
                    total,
                    branch_code,
                    f"Sedang memproses branch {normalized_code}...",
                )
            print(
                f"[INFO] Unit Kerja {index}/{len(branch_codes)}: "
                f"{normalized_code} "
                f"(Branch.md: {branch_code})"
            )
            if not self._pilih_unit_kerja(branch_code):
                dilewati.append(branch_code)
                if progress_callback:
                    progress_callback(
                        index,
                        total,
                        branch_code,
                        f"Branch {normalized_code} tidak ditemukan; dilewati.",
                    )
                continue
            self._unduh_excel(tanggal, branch_code, output_dir=output_dir)
            berhasil += 1
            if progress_callback:
                progress_callback(
                    index,
                    total,
                    branch_code,
                    f"Branch {normalized_code} berhasil diunduh.",
                )

        print(
            f"[SELESAI] Berhasil diunduh: {berhasil}; "
            f"tidak ditemukan/dilewati: {len(dilewati)}."
        )
        if dilewati:
            print("[INFO] Branch yang dilewati: " + ", ".join(dilewati))
        if status_callback:
            status_callback(
                f"Proses selesai: {berhasil} berhasil, "
                f"{len(dilewati)} branch dilewati."
            )

    def tutup(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()


def main():
    downloader = TL506Downloader()
    try:
        tanggal, branch_codes = downloader.baca_branch_md(BRANCH_FILE)
        downloader.buka()
        downloader.proses(tanggal, branch_codes)
    except PlaywrightTimeoutError as error:
        print(f"[TIMEOUT] Elemen BRISIM tidak ditemukan:\n{error}")
    except Exception as error:
        print(f"[ERROR] {error}")
    finally:
        downloader.tutup()


if __name__ == "__main__":
    main()
