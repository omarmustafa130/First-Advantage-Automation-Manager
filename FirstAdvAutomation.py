from playwright.sync_api import sync_playwright
import time
import re
import pandas as pd

def fill_shadow_input(component, value, frame):
    shadow_input = frame.locator(component).evaluate_handle("el => el.shadowRoot.querySelector('input')")
    shadow_input.as_element().fill(value)

def main(index, row, CLIENT_ID, USER_ID, PASSWORD, SEC_QUESTION, first_name, last_name, email, company_id, location, position_type, csp_id, package_text):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://enterprise.fadv.com/")
        time.sleep(5)

        # Login steps
        frame = page.frame_locator("#new-login-iframe")
        fill_shadow_input("fadv-input#login-client-id-input", CLIENT_ID, frame)
        fill_shadow_input("fadv-input#login-user-id-input", USER_ID, frame)
        fill_shadow_input("fadv-input#login-password-input", PASSWORD, frame)
        page.frame_locator("#new-login-iframe").locator("fadv-button#login-button").click()
        time.sleep(2)
        # Handle Proceed button in iframe
        frame = page.frame_locator("#new-login-iframe")
        fill_shadow_input("fadv-input#security-question-input", SEC_QUESTION, frame)
        page.frame_locator("#new-login-iframe").locator("fadv-button#security-question-submit-button").click()
        time.sleep(2)
        try:
            # Wait for the iframe and switch to it
            page.wait_for_selector("iframe#new-login-iframe", timeout=5000)
            frame_locator = page.frame_locator("iframe#new-login-iframe")
            
            # Wait for and click the Proceed button using text matching
            proceed_button = frame_locator.get_by_text("Proceed", exact=True)
            proceed_button.click(timeout=30000)
        except:
            pass

        # Continue with other actions
        try:
            #page.wait_for_selector("iframe#new-login-iframe", timeout=30000)   
            page.frame_locator("#new-login-iframe").locator("fadv-button#notice-agree-button").click()
            
        except Exception as e:
            # Fallback to JavaScript click
            page.evaluate("document.getElementById('agreeBtn').click()")

        
        time.sleep(30)
        # Expand the "Profile Advantage" menu if it's closed
        page.locator("div#EE_MENU_PROFILE_ADVANTAGE > table > tbody > tr:first-child a").click()

        # Wait for "New Subject" to become visible, then click it
        page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").wait_for(state="visible")

        page.locator("div#EE_MENU_PROFILE_ADVANTAGE_NEW_SUBJECT span", has_text="New Subject").click()
        time.sleep(20)
        
        # Fill form fields
        page.locator("input#CDC_NEW_SUBJECT_FIRST_NAME").fill(first_name)
        page.locator("input#CDC_NEW_SUBJECT_LAST_NAME").fill(last_name)
        page.locator("input#CDC_NEW_SUBJECT_EMAIL_ADDRESS").fill(email)

        time.sleep(25)
        # Select CSP ID from dropdown
        page.locator("select#Order\\.Info\\.RefID3").select_option(str(csp_id))
        time.sleep(3)


        # Find the matching package value
        package_options = page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL option").all_text_contents()
        
        # Extract the option value (e.g., "2426" for "A - NON CDL DRIVER PKG + PHYSICAL AND DRUG (MC)")
        matching_value = None
        for option in package_options:
            if package_text in option:
                matching_value = page.locator(f"select#CDC_NEW_SUBJECT_PACKAGE_LABEL option", has_text=option).get_attribute("value")
                break

        # Select the matching package option
        if matching_value:
            page.locator("select#CDC_NEW_SUBJECT_PACKAGE_LABEL").select_option(matching_value)
        
        time.sleep(3)

        # --- Company ID Dropdown ---
        page.locator("select#Company\\ ID").select_option(label=company_id)
        # --- Facility ID Mapping ---
        location_map = {
            "wilson": "00256 - WILSON, NC",
            "new hill": "00250 - NEW HILL, NC",
            "greenville": "00278 - EAST CAROLINA, NC"
        }
        facility_option = location_map.get(location)
        if facility_option:
            page.locator("select#Facility\\ ID").select_option(label=facility_option)
            time.sleep(3)

        # --- Position Type ---
        page.locator("select#Position\\ Type").select_option(label=position_type)
        time.sleep(3)

        page.get_by_text("Send", exact=True).click()
        time.sleep(10)
         # ✅ **Mark as Completed**
        df.at[index, "Status"] = "Completed"
        print(f"✔ Successfully completed: {full_name}")
        
        
        browser.close()

if __name__ == '__main__':
    CLIENT_ID = "CLIENT-ID"
    USER_ID = "USER-ID"
    PASSWORD = "PASSWORD"
    SEC_QUESTION = "SEC Question"
    csv_url = "Google spreadsheet URL"
    df = pd.read_csv(csv_url)
    for index, row in df.iterrows():

        full_name = row["Full Name"].strip()
        
        # Split name at the first space
        split = full_name.split(" ", 1)
        first_name = split[0]
        last_name = split[1] if len(split) > 1 else ""

        email = row["Email"]
        company_id = row["Company ID"]  # e.g. "300 - ISP Pickup & Delivery"
        location = row["Location"].strip().lower()  # e.g. "Wilson"
        position_type = row["Position Type"]  # e.g. "A - P&D Non-CDL Driver"
        csp_id = row["CSP ID"]
        package_text = row["Package"]
        
        print(f'Processing index: {index+1}\nFirst Name: {first_name}\nLast Name: {last_name}\nEmail: {email}\nCompany ID: {company_id}\nLocation: {location}\nPosition Type: {position_type}\nCSP ID: {csp_id}\nPackage: {package_text}\n\n')
        
        main(index, row, CLIENT_ID, USER_ID, PASSWORD, SEC_QUESTION, first_name, last_name, email, company_id, location, position_type, csp_id, package_text)
