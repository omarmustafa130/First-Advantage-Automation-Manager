# automation_worker.py (updated for service account Google Sheet updates)
from playwright.sync_api import sync_playwright
import time
import threading
import gspread
from oauth2client.service_account import ServiceAccountCredentials

class FirstAdvantageAutomation:
    def __init__(self):
        self.CLIENT_ID = ""
        self.USER_ID = ""
        self.PASSWORD = ""
        self.SEC_QUESTION = ""
        self.sheet_url = ""
        self.running = False
        self.processed = 0
        self.total = 0
        self.thread = None
        self.status = "Stopped"
    def set_status(self, status_text):
        self.status = status_text

    def load_sheet(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("service-account.json", scope)
        client = gspread.authorize(creds)
        return client.open_by_url(self.sheet_url).sheet1

    def get_status(self):
        return {
            "processed": self.processed,
            "total": self.total,
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
                sheet = self.load_sheet()
                data = sheet.get_all_records()
                headers = sheet.row_values(1)
                status_col = headers.index("Status") + 1

                self.total = len(data)
                self.processed = sum(1 for row in data if str(row.get("Status", "")).strip().lower() == "completed")

                for index, row in enumerate(data):
                    if not self.running:
                        break
                    if str(row.get("Status", "")).strip().lower() == "completed":
                        continue

                    # Flag to detect if row was fully processed
                    successfully_processed = self.process_row(index, row)
                    if successfully_processed and self.running:
                        sheet.update_cell(index + 2, status_col, "Completed")
                        self.processed += 1  # move this here
                    time.sleep(2)

            except Exception as e:
                print(f"Error: {e}")

            # Wait a bit before checking the sheet again
            time.sleep(10)



    def process_row(self, index, row):
        try:
            full_name = row["Full Name"].strip()
            split = full_name.split(" ", 1)
            first_name = split[0]
            last_name = split[1] if len(split) > 1 else ""
            email = row["Email"]
            company_id = row["Company ID"]
            location = row["Location"].strip().lower()
            position_type = row["Position Type"]
            csp_id = row["CSP ID"]
            package_text = row["Package"]

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

                time.sleep(20)
                page.locator("div#EE_MENU_PROFILE_ADVANTAGE > table > tbody > tr:first-child a").click()
                page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").click()
                time.sleep(15)

                page.locator("input#CDC_NEW_SUBJECT_FIRST_NAME").fill(first_name)
                page.locator("input#CDC_NEW_SUBJECT_LAST_NAME").fill(last_name)
                page.locator("input#CDC_NEW_SUBJECT_EMAIL_ADDRESS").fill(email)
                page.locator("input#gwt-uid-685").check()

                page.locator("select#Order\\.Info\\.RefID3").select_option(str(csp_id))

                options = page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL option").all_text_contents()
                for option in options:
                    if package_text in option:
                        value = page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL option", has_text=option).get_attribute("value")
                        page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL").select_option(value)
                        break

                page.locator("select#Company\\ ID").select_option(label=company_id)
                location_map = {
                    "wilson": "00256 - WILSON, NC",
                    "new hill": "00250 - NEW HILL, NC",
                    "greenville": "00278 - EAST CAROLINA, NC"
                }
                facility_option = location_map.get(location)
                if facility_option:
                    page.locator("select#Facility\\ ID").select_option(label=facility_option)

                page.locator("select#Position\\ Type").select_option(label=position_type)
                page.get_by_text("Send", exact=True).click()
                time.sleep(10)
                return True
        except Exception as e:
            print(f"Row {index} failed: {e}")
            return False

    def fill_shadow_input(self, component, value, frame):
        shadow_input = frame.locator(component).evaluate_handle("el => el.shadowRoot.querySelector('input')")
        shadow_input.as_element().fill(value)

automation_instance = FirstAdvantageAutomation()