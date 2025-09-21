from playwright.sync_api import sync_playwright
import time as t
import threading
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pytz
from datetime import datetime, timedelta, time

class FirstAdvantageAutomation:
    def __init__(self):
        self._lock = threading.Lock()  # prevent double-starts
        self.CLIENT_ID = ""
        self.USER_ID = ""
        self.PASSWORD = ""
        self.SEC_QUESTION = ""
        self.sheet_url = ""
        self.running = False
        self.thread = None
        self.status = "Stopped"
        self.forced = False
        # In-memory counters
        self.applicants_total = 0
        self.applicants_processed = 0
        self.pending_total = 0
        self.pending_processed = 0
        self.orders_placed = 0

    def set_status(self, status_text):
        self.status = status_text

    def load_sheets(self):
        """
        This method just returns the 'Applicants', 'Pending Review', and 'False Positive' worksheets,
        with a small retry in case of transient errors.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_name("service-account.json", scope)
                client = gspread.authorize(creds)
                spreadsheet = client.open_by_url(self.sheet_url)
                return {
                    "Applicants": spreadsheet.worksheet("Applicants"),
                    "Pending Review": spreadsheet.worksheet("Pending Review"),
                    "False Positives": spreadsheet.worksheet("False Positives") # Add this line
                }
            except Exception as e:
                print(f"Sheet load error (attempt {attempt+1}): {str(e)}")
                t.sleep(2 * (attempt + 1))  # Exponential backoff
        raise Exception("Failed to load sheets after retries.")
    
    def _click_pending_result_row(self, page, email, name=None, timeout=20000):
        """
        After 'Search', waits for results and clicks the subject row.
        Prefers locating by the email icon's title attribute (stable).
        Fallbacks to name text, then first row.
        """
        # Wait for the results table to appear
        results = page.locator("table.GOIVD5ICHFF")
        results.wait_for(state="visible", timeout=timeout)

        # Wait until at least one data row exists (GWT renders asynchronously)
        page.wait_for_function(
            "document.querySelectorAll('table.GOIVD5ICHFF tr.standard').length > 0",
            timeout=timeout,
        )

        # 1) Preferred: locate the email icon by title (unique & stable)
        email_icon = results.locator(f"img.gwt-Image.pointer[title='{email}']").first
        if email_icon.count() > 0:
            row = email_icon.locator("xpath=ancestor::tr[1]")
            # Click the name cell inside this row (the clickable one has 'pointer')
            name_cell = row.locator("css=div.pointer").first
            name_cell.click()
            return True

        # 2) Fallback: locate by the subject (name) text if provided
        if name:
            try:
                results.locator(f"css=div.pointer:has-text('{name}')").first.click()
                return True
            except Exception:
                pass

        # 3) Fallback: click the first data row's clickable cell
        try:
            first_row_clickable = results.locator("tr.standard >> css=div.pointer").first
            first_row_clickable.click()
            return True
        except Exception:
            return False


    def get_status(self):
        """
        Returns the last known counters (in memory) without re-loading the sheet.
        This keeps /status calls fast and stable.
        """
        return {
            "applicants_total": self.applicants_total,
            "applicants_processed": self.applicants_processed,
            "pending_total": self.pending_total,
            "pending_processed": self.pending_processed,
            "orders_placed": self.orders_placed,
            "client_id": self.CLIENT_ID,
            "user_id": self.USER_ID,
            "sheet_url": self.sheet_url,
            "status": self.status
        }

    def update_credentials(self, client_id, user_id, password, sec_question, sheet_url):
        self.CLIENT_ID = client_id
        self.USER_ID = user_id
        self.PASSWORD = password
        self.SEC_QUESTION = sec_question
        self.sheet_url = sheet_url

    def run(self, force=False):
        # NEW: reentrancy guard so we can't start two workers
        with self._lock:
            if self.running:
                print("Already running.")
                return
            self.running = True

        self.status = "Running" if not force else "Running (Forced)"
        self.forced = force

        # On start, do an initial load to set counters (best-effort)
        try:
            sheets = self.load_sheets()
            # Applicants
            applicants_data = sheets["Applicants"].get_all_records()
            self.applicants_total = len(applicants_data)
            self.applicants_processed = sum(
                1 for row in applicants_data
                if str(row.get("Status", "")).strip().lower() == "completed"
            )
            # Pending
            pending_data = sheets["Pending Review"].get_all_records()
            self.pending_total = len(pending_data)
            self.pending_processed = sum(
                1 for row in pending_data
                if str(row.get("Status", "")).strip().lower() == "completed"
            )
            self.orders_placed = sum(
                1 for row in pending_data
                if str(row.get("OrderStatus", "")).strip().lower() == "placed"
            )
        except Exception as e:
            print("Error loading initial sheet counts:", e)

        # Start processing in a background thread
        self.thread = threading.Thread(target=self.process, daemon=True)
        self.thread.start()


    def stop(self):
        self.running = False
        self.status = "Stopped"
        self.forced = False  # Add this line
        if self.thread:
            self.thread.join()
        self.thread = None
    def process(self):
        while self.running:
            try:
                forced_mode = self.forced

                # Time window logic
                est = pytz.timezone('US/Eastern')
                current_time = datetime.now(est)
                within_hours = 8 <= current_time.hour < 20

                print(f"[DEBUG] current_time={current_time}, forced_mode={forced_mode}, "
                    f"within_hours={within_hours}, running={self.running}")

                # Outside hours and NOT forced → schedule resume at 8am and stop this worker
                if (not forced_mode) and (not within_hours):
                    self.set_status("Sleeping until 8am EST")
                    next_run = est.localize(datetime.combine(
                        current_time.date() + timedelta(days=1 if current_time.hour >= 20 else 0),
                        time(8, 0)
                    ))
                    wait_seconds = (next_run - current_time).total_seconds()
                    print(f"[DEBUG] Scheduling next run in {wait_seconds} seconds")
                    threading.Timer(wait_seconds, self.run).start()
                    self.running = False
                    break

                # If we were forced but we’re now within hours, revert to normal
                if forced_mode and within_hours:
                    self.set_status("Running (Normal hours)")
                    self.forced = False
                    forced_mode = False

                # ---- Sheet handles and column indices (do this FIRST every loop) ----
                sheets = self.load_sheets()

                applicants_sheet = sheets["Applicants"]
                pending_sheet = sheets["Pending Review"]
                false_positive_sheet = sheets["False Positives"]

                applicants_headers = applicants_sheet.row_values(1)
                pending_headers = pending_sheet.row_values(1)

                try:
                    status_col_app = applicants_headers.index("Status") + 1
                except ValueError:
                    raise Exception("'Status' column not found in Applicants")

                try:
                    status_col_pending = pending_headers.index("Status") + 1
                except ValueError:
                    raise Exception("'Status' column not found in Pending Review")

                # ---- False Positives pass (same logic, now uses known status_col_app) ----
                fp_updates = []
                try:
                    fp_data = false_positive_sheet.get_all_records()
                    if fp_data:
                        applicants_data_for_fp = applicants_sheet.get_all_records()
                        for i, app_row in enumerate(applicants_data_for_fp):
                            # build a quick lookup of name/email for this app_row
                            app_name = str(app_row.get("Full Name", "")).strip().lower()
                            app_email = str(app_row.get("Email", "")).strip().lower()

                            for fp_row in fp_data:
                                name_to_match = str(fp_row.get("Name", "")).strip().lower()
                                email_to_match = str(fp_row.get("Email Address", "")).strip().lower()

                                if app_name == name_to_match and app_email == email_to_match:
                                    # Only reset if currently Completed
                                    if str(app_row.get("Status", "")).strip().lower() == "completed":
                                        fp_updates.append({
                                            'range': gspread.utils.rowcol_to_a1(i + 2, status_col_app),
                                            'values': [['']]
                                        })
                                        print(f"[INFO] Prepared to reset status for {app_name}.")
                                    break
                    if fp_updates:
                        applicants_sheet.batch_update(fp_updates)
                        print(f"[INFO] Batch update for {len(fp_updates)} false positives completed.")
                except Exception as e:
                    print(f"[WARN] False positives phase skipped due to error: {e}")

                # ---- Applicants phase (two-step status: Processing → Completed/Error) ----
                applicants_data = applicants_sheet.get_all_records()
                self.applicants_total = len(applicants_data)
                self.applicants_processed = sum(
                    1 for row in applicants_data
                    if str(row.get("Status", "")).strip().lower() == "completed"
                )

                to_process_applicants = [
                    (i, row) for i, row in enumerate(applicants_data)
                    if str(row.get("Status", "")).strip().lower() not in ("completed", "processing")
                ]

                did_any = False
                if to_process_applicants:
                    did_any = True
                    for i, row in to_process_applicants:
                        if not self.running:
                            break
                        row_index = i + 2  # account for header

                        # Phase 1: immediately mark as Processing to avoid duplicate work on crashes
                        try:
                            applicants_sheet.update_cell(row_index, status_col_app, "Processing")
                        except Exception as e:
                            print(f"[WARN] Applicants row {i} could not be marked Processing: {e}")

                        success = False
                        try:
                            success = self.process_row(i, row, is_pending_review=False)
                        except Exception as e:
                            print(f"[ERROR] Applicants row {i} crashed: {e}")

                        # Phase 2: finalize
                        try:
                            if success:
                                applicants_sheet.update_cell(row_index, status_col_app, "Completed")
                                self.applicants_processed += 1
                            else:
                                applicants_sheet.update_cell(row_index, status_col_app, "Error")
                        except Exception as e:
                            print(f"[WARN] Applicants row {i} final status write failed: {e}")

                        t.sleep(2)  # small pacing

                # ---- Pending Review phase (only if nothing pending in Applicants) ----
                if not did_any:
                    pending_data = pending_sheet.get_all_records()

                    self.pending_total = len(pending_data)
                    self.pending_processed = sum(
                        1 for row in pending_data
                        if str(row.get("Status", "")).strip().lower() == "completed"
                    )

                    to_process_pending = [
                        (i, row) for i, row in enumerate(pending_data)
                        if str(row.get("Status", "")).strip().lower() not in ("completed", "processing")
                    ]

                    for i, row in to_process_pending:
                        if not self.running:
                            break
                        row_index = i + 2

                        # Phase 1
                        try:
                            pending_sheet.update_cell(row_index, status_col_pending, "Processing")
                        except Exception as e:
                            print(f"[WARN] Pending row {i} could not be marked Processing: {e}")

                        success = False
                        try:
                            success = self.process_row(i, row, is_pending_review=True)
                        except Exception as e:
                            print(f"[ERROR] Pending row {i} crashed: {e}")

                        # Phase 2
                        try:
                            if success:
                                pending_sheet.update_cell(row_index, status_col_pending, "Completed")
                                self.pending_processed += 1
                            else:
                                pending_sheet.update_cell(row_index, status_col_pending, "Error")
                        except Exception as e:
                            print(f"[WARN] Pending row {i} final status write failed: {e}")

                        t.sleep(2)

            except Exception as e:
                print(f"[ERROR] process loop: {e}")

            # Loop pacing
            t.sleep(10)

    def check_false_positives(self, sheets):
        """
        Checks the 'False Positives' sheet and returns a list of updates
        for the 'Applicants' sheet.
        """
        print("[INFO] Checking for false positives...")
        updates = []
        try:
            false_positive_sheet = sheets["False Positives"]
            if not false_positive_sheet:
                print("[WARNING] 'False Positives' sheet not found. Skipping check.")
                return updates

            false_positive_data = false_positive_sheet.get_all_records()
            if not false_positive_data:
                print("[INFO] 'False Positives' sheet is empty.")
                return updates

            applicants_sheet = sheets["Applicants"]
            applicants_data = applicants_sheet.get_all_records() 
            applicants_headers = applicants_sheet.row_values(1)
            status_col_app = applicants_headers.index("Status") + 1

            reset_count = 0
            for fp_row in false_positive_data:
                name_to_match = fp_row.get("Name", "").strip().lower()
                email_to_match = fp_row.get("Email Address", "").strip().lower()

                for i, app_row in enumerate(applicants_data):
                    if (
                        app_row.get("Full Name", "").strip().lower() == name_to_match
                        and app_row.get("Email", "").strip().lower() == email_to_match
                    ):
                        # The value of row_index needs to be adjusted for the API call
                        row_index = i + 2 
                        current_status = applicants_sheet.cell(row_index, status_col_app).value
                        if str(current_status).strip().lower() == "completed":
                            # Add the update to a list instead of applying it immediately
                            updates.append({'range': gspread.utils.rowcol_to_a1(row_index, status_col_app), 'values': [['']]})
                            reset_count += 1
                            print(f"[INFO] Prepared to reset status for {name_to_match}.")
                            break

            print(f"[INFO] Completed false positive check. Found {reset_count} row(s) to reset.")
            return updates
        except Exception as e:
            print(f"[ERROR] Failed to check false positives: {e}")
            return updates

    def check_checkbox_by_caption(self, page, caption_text: str, timeout: int = 10000):
        """
        Finds a checkbox by the visible caption (e.g., 'CC: Recruiter on Invitation Email')
        and ensures it's checked. Works even with duplicated IDs.
        """
        # Prefer robust CSS :has() (Playwright supports it)
        locator = page.locator(
            f"tr:has(div.GOIVD5ICIOC:has-text('{caption_text}')) input[type='checkbox']"
        ).first

        try:
            locator.wait_for(state="attached", timeout=timeout)
        except Exception:
            # Fallback to XPath if needed
            locator = page.locator(
                "xpath=//div[contains(@class,'GOIVD5ICIOC') and "
                f"normalize-space()='{caption_text}']/ancestor::tr[1]//input[@type='checkbox']"
            ).first
            locator.wait_for(state="attached", timeout=timeout)

        if not locator.is_checked():
            locator.check()

    def process_row(self, index, row, is_pending_review=False):
        try:
            full_name = row["Full Name"].strip()
            split = full_name.split(" ", 1)
            first_name = split[0]
            last_name = split[1] if len(split) > 1 else ""
            email = row["Email"]
            company_id = row.get("Company ID", "")
            location = row.get("Location", "").strip().lower()
            position_type = row.get("Position Type", "")
            csp_id = row.get("CSP ID", "")
            package_text = row.get("Package", "")

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://enterprise.fadv.com/")
                t.sleep(5)

                frame = page.frame_locator("#new-login-iframe")
                self.fill_shadow_input("fadv-input#login-client-id-input", self.CLIENT_ID, frame)
                self.fill_shadow_input("fadv-input#login-user-id-input", self.USER_ID, frame)
                self.fill_shadow_input("fadv-input#login-password-input", self.PASSWORD, frame)
                frame.locator("fadv-button#login-button").click()
                t.sleep(2)
                self.fill_shadow_input("fadv-input#security-question-input", self.SEC_QUESTION, frame)
                frame.locator("fadv-button#security-question-submit-button").click()
                t.sleep(2)

                try:
                    page.frame_locator("#new-login-iframe").get_by_text("Proceed", exact=True).click(timeout=10000)
                except:
                    pass
                try:
                    frame.locator("fadv-button#notice-agree-button").click()
                except:
                    page.evaluate("document.getElementById('agreeBtn').click()")

                # Wait for main menu to load
                t.sleep(30)
                page.locator("div#EE_MENU_PROFILE_ADVANTAGE > table > tbody > tr:first-child a").click()

                if not is_pending_review:
                    # Applicants flow
                    page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").wait_for(state="visible")
                    page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").click()
                    t.sleep(20)
                    page.locator("input#CDC_NEW_SUBJECT_FIRST_NAME").fill(first_name)
                    page.locator("input#CDC_NEW_SUBJECT_LAST_NAME").fill(last_name)
                    page.locator("input#CDC_NEW_SUBJECT_EMAIL_ADDRESS").fill(email)
                    self.check_checkbox_by_caption(page, "CC: Recruiter on Invitation Email")

                    t.sleep(25)
                    page.locator("select#Order\\.Info\\.RefID3").select_option(str(csp_id))
                    t.sleep(3)

                    package_options = page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL option").all_text_contents()
                    for option in package_options:
                        if package_text in option:
                            value = page.locator(
                                "select#CDC_NEW_SUBJECT_PACKAGE_LABEL option", has_text=option
                            ).get_attribute("value")
                            page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL").select_option(value)
                            break
                    t.sleep(3)
                    page.locator("select#Company\\ ID").select_option(label=company_id)

                    location_map = {
                        "wilson": "00256 - WILSON, NC",
                        "new hill": "00250 - NEW HILL, NC",
                        "greenville": "00278 - EAST CAROLINA, NC"
                    }
                    facility_option = location_map.get(location)
                    if facility_option:
                        page.locator("select#Facility\\ ID").select_option(label=facility_option)
                        t.sleep(3)
                    page.locator("select#Position\\ Type").select_option(label=position_type)
                    t.sleep(3)
                    page.get_by_text("Send", exact=True).click()
                    try:
                        page.get_by_text("Send", exact=True).click()
                    except:
                        pass
                    t.sleep(15)
                else:
                    # Pending Review flow
                    page.get_by_text("Find Subject", exact=True).click()
                    page.locator("input#CDC_SEARCH_SUBJECT_EMAIL_ADDRESS_LBL").fill(email)
                    page.locator("select#CDC_SEARCH_SUBJECT_PROFILE_STATUS_LBL").select_option(label="Pending For Review")
                    t.sleep(3)
                    page.locator("div.html-face", has_text="Search").first.wait_for(state="visible", timeout=10000)
                    page.locator("div.html-face", has_text="Search").first.click()

                    # Wait for results & click the row by email/name (robust)
                    found = self._click_pending_result_row(page, email=email, name=full_name)
                    if not found:
                        # No result – treat as soft failure so the row becomes "Error" and doesn't loop forever
                        raise Exception(f"No pending result row found for email '{email}'")

                    page.locator("select#CDC_SUBJECT_DETAIL_ACTIONS").select_option("REVIEW_AND_PLACE_ORDER")
                    t.sleep(1)
                    ok_button = page.locator("div.eePushButtonSmall-up >> div.html-face", has_text="OK")
                    ok_button.wait_for(state="visible", timeout=10000)
                    ok_button.click()
                    t.sleep(10)

                browser.close()
                return True
        except Exception as e:
            print(f"Row {index} failed: {e}")
            return False

    def fill_shadow_input(self, component, value, frame):
        shadow_input = frame.locator(component).evaluate_handle("el => el.shadowRoot.querySelector('input')")
        shadow_input.as_element().fill(value)

    def __del__(self):
        self.CLIENT_ID = ""
        self.PASSWORD = ""
        self.SEC_QUESTION = ""
        self.stop()
automation_instance = FirstAdvantageAutomation()
