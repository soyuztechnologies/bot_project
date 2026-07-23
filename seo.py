import os
import time
import random
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# ==========================================
# ⚙️ CONFIGURATION & DATA
# ==========================================
KEYWORDS = [
    "abap on cloud training", "sap analytics cloud", "sap btp training",
    "sap build studio", "sap build training", "sap certification",
    "sap datasphere", "sap fiori administration", "sap fiori training",
    "sap gen ai training", "sap generative ai", "sap rap training"
]

TARGET_DOMAIN = "anubhavtrainings.com"
MAX_PAGES = 20
# ==========================================
# 🛠️ HELPER FUNCTIONS (Modularity)
# ==========================================

def random_sleep(min_sec, max_sec):
    """Generates a random human-like delay."""
    time.sleep(random.uniform(min_sec, max_sec))

def setup_browser():
    """Initializes and returns the undetected Chrome browser."""
    print("🚀 Initializing browser...")
    driver = uc.Chrome(version_main=150)
    driver.maximize_window()
    return driver

def human_typing(element, text):
    """Simulates real human typing speed (Optimized for faster typing)."""
    for char in text:
        element.send_keys(char)
        random_sleep(0.05, 0.15)

def search_on_google(driver, keyword):
    """Navigates to Google and performs the search."""
    print("🌐 Opening Google...")
    driver.get("https://www.google.com")
    random_sleep(2, 3) 

    search_box = driver.find_element(By.NAME, "q")
    print(f"🎯 Typing the keyword -> '{keyword}'")
    human_typing(search_box, keyword)
    
    search_box.send_keys(Keys.RETURN) # Press Enter to search
    random_sleep(2, 3) 

def scroll_and_click(driver, element):
    """Safely scrolls to an element and clicks it."""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    random_sleep(1.0, 1.5) 
    # Using javascript click as the safest option to avoid interception
    driver.execute_script("arguments[0].click();", element)

def go_to_next_page(driver):
    """Handles all Google pagination logic (Next, More Results, Infinite Scroll). Returns True if successful."""
    try:
        # 1. Standard 'Next' button
        next_button = driver.find_element(By.ID, "pnnext")
        scroll_and_click(driver, next_button)
        return True
    except:
        try:
            # 2. 'More results' button
            print("'Next' button not found. Looking for 'More results'...")
            more_btn = driver.find_element(By.XPATH, "//*[contains(., 'More results') or contains(., 'More search results') or contains(., 'और परिणाम')]")
            scroll_and_click(driver, more_btn)
            return True
        except:
            # 3. Infinite Scroll Fallback
            try:
                print("Buttons not found. Trying 'Infinite Scroll'...")
                old_link_count = len(driver.find_elements(By.XPATH, "//a"))
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                random_sleep(2, 3) 
                
                new_link_count = len(driver.find_elements(By.XPATH, "//a"))
                
                if new_link_count > old_link_count:
                    return True  # New results loaded successfully
                else:
                    print("No new results loaded. Reached the end of Google results.")
                    return False # No more results available
            except Exception as e:
                return False

def find_target_domain(driver, target_domain, max_pages):
    """Scans search results across pages to find and click the target domain."""
    print(f"🔍 Searching for URLs containing '{target_domain}'...")
    
    # Loop through the search result pages until the target domain is found or max pages are reached 
    for current_page in range(1, max_pages + 1):
        print(f"--- Checking Page {current_page} ---")
        
        # Extract all anchor tags on the current page
        links = driver.find_elements(By.XPATH, "//a")
        
        for link in links:
            try:
                href = link.get_attribute("href") 
                
                # Check if href exists and contains the target domain
                if href and target_domain in href: 
                    print(f"🎉 Target Domain found: '{href}'")
                    print("Clicking on it now...")
                    scroll_and_click(driver, link)
                    return True # Website found and clicked, exit the function successfully
            except:
                continue # Ignore errors (like stale elements) and check the next link
        
        # If target domain is not on the current page, go to the next page
        print("Domain not found. Scrolling down to check the next page...")
        if not go_to_next_page(driver):
            break # Exit the loop if no more pages are available
        
        random_sleep(1.5, 2.5) 
        
    return False # Target domain not found after checking all max_pages

def simulate_human_reading(driver):
    """Simulates a human reading and scrolling on the target website to reduce bounce rate."""
    print("✅ Website loaded successfully. Simulating human reading behavior...")
    random_sleep(8,10)
    scroll_depth = random.randint(500, 1200) 
    driver.execute_script(f"window.scrollTo(0, {scroll_depth});")
    random_sleep(8,10) 
    
    driver.execute_script(f"window.scrollTo({scroll_depth}, {scroll_depth + 600});")
    random_sleep(8,10)


# ==========================================
# 🚀 MAIN EXECUTION BLOCK (Batch Processing)
# ==========================================

def main():
    print(f"Total keywords to process: {len(KEYWORDS)}")
    
    # 1. Shuffle keywords to randomize search patterns and avoid bot detection
    random.shuffle(KEYWORDS)
    
    # 2. Iterate through all keywords one by one
    for index, current_keyword in enumerate(KEYWORDS, start=1):
        print(f"\n=======================================================")
        print(f"🔄 Starting Task {index}/{len(KEYWORDS)} for keyword: '{current_keyword}'")
        print(f"=======================================================\n")
        
        driver = None
        
        try:
            # Initialize a FRESH browser session for every keyword to clear history/cookies
            driver = setup_browser()
            
            search_on_google(driver, current_keyword)
            
            # Search for the website (returns True if found, False otherwise)
            website_found = find_target_domain(driver, TARGET_DOMAIN, MAX_PAGES)
            
            if website_found:
                simulate_human_reading(driver)
            else:
                # If the website is not found, skip gracefully without crashing
                print(f"⏭️ SKIP: '{TARGET_DOMAIN}' not found for '{current_keyword}'. Moving to the next keyword...")
                
        except Exception as e:
            # Catch unexpected errors to prevent the entire batch from crashing
            print(f"⚠️ An error occurred during '{current_keyword}': {e}")
            
        finally:
            print(f"🛑 Finished task for '{current_keyword}'. Closing browser...")
            time.sleep(1)
            if driver:
                try:
                    driver.quit() 
                except OSError:
                    pass
        
        # 3. Wait between processing keywords to mimic human behavior
        if index < len(KEYWORDS):
            wait_time = random.randint(5, 10) 
            print(f"⏳ Waiting for {wait_time} seconds before starting the next keyword...\n")
            time.sleep(wait_time)

    # Exit the script safely once all keywords are processed
    print("\n✅✅ ALL KEYWORDS PROCESSED SUCCESSFULLY! EXITING SCRIPT... ✅✅")
    os._exit(0)

# ==========================================================================================================
# Standard Python idiom to ensure the main function runs only when executed directly
if __name__ == "__main__":
    main()