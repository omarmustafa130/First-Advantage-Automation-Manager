from playwright.sync_api import sync_playwright
import time
import threading
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import pytz

class FirstAdvantageAutomation:
    def __init__(self):
        self.CLIENT_ID = ""
        self.USER_ID = ""
        self.PASSWORD = ""
        self.SEC_QUESTION = ""
        self.sheet_url = ""
        self.running = False
        self.thread = None
        self.status = "Stopped"
        
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
        This method just returns the 'Applicants' and 'Pending Review' worksheets,
        with a small retry in case of transient errors.
        """
        max_retries = 3
        for _ in range(max_retries):
            try:
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_name("service-account.json", scope)
                client = gspread.authorize(creds)
                spreadsheet = client.open_by_url(self.sheet_url)
                return {
                    "Applicants": spreadsheet.worksheet("Applicants"),
                    "Pending Review": spreadsheet.worksheet("Pending Review")
                }
            except:
                time.sleep(2)
        raise Exception("Failed to load sheets after retries.")

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

    def run(self):
        if self.running:
            print("Already running.")
            return
        self.running = True
        self.status = "Running"
        
        # On start, do an initial load to set counters
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
        self.thread = threading.Thread(target=self.process)
        self.thread.start()

    def stop(self):
        self.running = False
        self.status = "Stopped"
        if self.thread:
            self.thread.join()
        self.thread = None

    def process(self):
        while self.running:
            try:
                est = pytz.timezone('US/Eastern')
                current_time = datetime.datetime.now(est)
                if not (8 <= current_time.hour < 20):
                    self.set_status("Sleeping until 8am EST")
                    self.running = False
                    break

                sheets = self.load_sheets()

                # Step 1: Process Applicants
                applicants_sheet = sheets["Applicants"]
                applicants_data = applicants_sheet.get_all_records()
                applicants_headers = applicants_sheet.row_values(1)
                status_col_app = applicants_headers.index("Status") + 1

                # Refresh totals
                self.applicants_total = len(applicants_data)
                self.applicants_processed = sum(
                    1 for row in applicants_data
                    if str(row.get("Status", "")).strip().lower() == "completed"
                )

                # Find rows not completed
                applicants_to_process = [
                    (i, row) for i, row in enumerate(applicants_data)
                    if str(row.get("Status", "")).strip().lower() != "completed"
                ]
                if applicants_to_process:
                    for index, row in applicants_to_process:
                        if not self.running:
                            break
                        success = self.process_row(index, row, is_pending_review=False)
                        if success:
                            applicants_sheet.update_cell(index + 2, status_col_app, "Completed")
                            self.applicants_processed += 1
                        time.sleep(3)
                else:
                    # Step 2: Try Pending Review
                    pending_sheet = sheets["Pending Review"]
                    pending_data = pending_sheet.get_all_records()
                    pending_headers = pending_sheet.row_values(1)
                    status_col_pending = pending_headers.index("Status") + 1

                    self.pending_total = len(pending_data)
                    self.pending_processed = sum(
                        1 for row in pending_data
                        if str(row.get("Status", "")).strip().lower() == "completed"
                    )

                    pending_to_process = [
                        (i, row) for i, row in enumerate(pending_data)
                        if str(row.get("Status", "")).strip().lower() == "new"
                    ]
                    if pending_to_process:
                        for index, row in pending_to_process:
                            if not self.running:
                                break
                            success = self.process_row(index, row, is_pending_review=True)
                            if success:
                                pending_sheet.update_cell(index + 2, status_col_pending, "Completed")
                                self.pending_processed += 1
                                # Possibly track 'OrderStatus' too?
                                # If you want to mark row["OrderStatus"] = "Placed"
                                # you'd do something similar to update_cell
                            time.sleep(3)
            except Exception as e:
                print(f"Error in process loop: {e}")

            # Wait 10s before next check
            time.sleep(10)

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
                time.sleep(5)

                frame = page.frame_locator("#new-login-iframe")
                self.fill_shadow_input("fadv-input#login-client-id-input", self.CLIENT_ID, frame)
                self.fill_shadow_input("fadv-input#login-user-id-input", self.USER_ID, frame)
                self.fill_shadow_input("fadv-input#login-password-input", self.PASSWORD, frame)
                frame.locator("fadv-button#login-button").click()
                time.sleep(2)
                self.fill_shadow_input("fadv-input#security-question-input", self.SEC_QUESTION, frame)
                frame.locator("fadv-button#security-question-submit-button").click()
                time.sleep(2)

                try:
                    page.frame_locator("#new-login-iframe").get_by_text("Proceed", exact=True).click(timeout=10000)
                except:
                    pass
                try:
                    frame.locator("fadv-button#notice-agree-button").click()
                except:
                    page.evaluate("document.getElementById('agreeBtn').click()")

                # Wait for main menu to load
                time.sleep(30)
                page.locator("div#EE_MENU_PROFILE_ADVANTAGE > table > tbody > tr:first-child a").click()

                if not is_pending_review:
                    # Applicants flow
                    page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").wait_for(state="visible")
                    page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").click()
                    time.sleep(20)
                    page.locator("input#CDC_NEW_SUBJECT_FIRST_NAME").fill(first_name)
                    page.locator("input#CDC_NEW_SUBJECT_LAST_NAME").fill(last_name)
                    page.locator("input#CDC_NEW_SUBJECT_EMAIL_ADDRESS").fill(email)
                    page.locator("input#gwt-uid-685").check()
                    time.sleep(25)
                    page.locator("select#Order\\.Info\\.RefID3").select_option(str(csp_id))
                    time.sleep(3)

                    package_options = page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL option").all_text_contents()
                    for option in package_options:
                        if package_text in option:
                            value = page.locator(
                                "select#CDC_NEW_SUBJECT_PACKAGE_LABEL option", has_text=option
                            ).get_attribute("value")
                            page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL").select_option(value)
                            break
                    time.sleep(3)
                    page.locator("select#Company\\ ID").select_option(label=company_id)

                    location_map = {
                        "wilson": "00256 - WILSON, NC",
                        "new hill": "00250 - NEW HILL, NC",
                        "greenville": "00278 - EAST CAROLINA, NC"
                    }
                    facility_option = location_map.get(location)
                    if facility_option:
                        page.locator("select#Facility\\ ID").select_option(label=facility_option)
                        time.sleep(3)
                    page.locator("select#Position\\ Type").select_option(label=position_type)
                    time.sleep(3)
                    page.get_by_text("Send", exact=True).click()
                    time.sleep(10)
                else:
                    # Pending Review flow
                    page.get_by_text("Find Subject", exact=True).click()
                    page.locator("input#CDC_SEARCH_SUBJECT_EMAIL_ADDRESS_LBL").fill(email)
                    page.locator("select#CDC_SEARCH_SUBJECT_PROFILE_STATUS_LBL").select_option(label="Pending For Review")
                    time.sleep(3)
                    page.locator("div.html-face", has_text="Search").first.wait_for(state="visible", timeout=10000)
                    page.locator("div.html-face", has_text="Search").first.click()
                    time.sleep(10)
                    page.locator("div.GA1IWM1DUC.GA1IWM1PKF.pointer").first.click()
                    page.locator("select#CDC_SUBJECT_DETAIL_ACTIONS").select_option("REVIEW_AND_PLACE_ORDER")
                    time.sleep(1)
                    ok_button = page.locator("div.eePushButtonSmall-up >> div.html-face", has_text="OK")
                    ok_button.wait_for(state="visible", timeout=10000)
                    ok_button.click()
                    time.sleep(10)

                browser.close()
                return True
        except Exception as e:
            print(f"Row {index} failed: {e}")
            return False

    def fill_shadow_input(self, component, value, frame):
        shadow_input = frame.locator(component).evaluate_handle("el => el.shadowRoot.querySelector('input')")
        shadow_input.as_element().fill(value)

automation_instance = FirstAdvantageAutomation()
