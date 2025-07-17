import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import json
import os
import time

# Setup logging to track what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_log.txt'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# FastAPI app setup
app = FastAPI(title="LinkedIn Automation Service")

# Models for request data
class LoginCredentials(BaseModel):
    email: str
    passwd: str

class ConnectProfile(BaseModel):
    profileLink: str

class SendMessage(BaseModel):
    profileLink: str
    messageText: str

# Manage browser sessions
class BrowserManager:
    def __init__(self):
        self.browser = None
        self.session_file = "cookies.json"
    
    def startBrowser(self):
        # Let's get a stealthy browser going
        try:
            chrome_options = uc.ChromeOptions()
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--start-maximized')
            
            self.browser = uc.Chrome(options=chrome_options, headless=False)
            # Sneaky trick to hide automation
            self.browser.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            logger.info("Browser started, ready to roll!")
        except Exception as e:
            logger.error(f"Oops, browser failed to start: {str(e)}")
            raise HTTPException(status_code=500, detail="Couldn't start the browser!")
    
    def saveCookies(self):
        # Save cookies to keep session alive
        if self.browser:
            cookies = self.browser.get_cookies()
            with open(self.session_file, 'w') as file:
                json.dump(cookies, file)
            logger.info("Cookies saved to file")
    
    def loadCookies(self):
        # Load cookies to restore session
        if os.path.exists(self.session_file) and self.browser:
            with open(self.session_file, 'r') as file:
                cookies = json.load(file)
            for cookie in cookies:
                self.browser.add_cookie(cookie)
            logger.info("Loaded cookies from file")
    
    def shutdown(self):
        # Clean up browser
        if self.browser:
            self.browser.quit()
            self.browser = None
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
            logger.info("Browser closed, all clean")

# Global browser instance
browser_mgr = BrowserManager()

def waitForElement(driver, by, value, timeout=10):
    # Wait for element to show up
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
        return element
    except:
        logger.error(f"Couldn't find element: {value}")
        raise HTTPException(status_code=404, detail=f"Element {value} not found")

def findConnectBtn(driver):
    # Try different ways to find the connect button
    possible_selectors = [
        "//button[contains(@aria-label, 'Invite') and contains(@aria-label, 'to connect')]",
        "//button[contains(text(), 'Connect')]",
        "//button[contains(@class, 'connect-button')]"
    ]
    
    for selector in possible_selectors:
        try:
            button = waitForElement(driver, By.XPATH, selector)
            if button.is_displayed():
                return button
        except:
            continue
    
    # Maybe it's in a dropdown?
    try:
        more_btn = waitForElement(driver, By.XPATH, "//button[@aria-label='More actions']")
        more_btn.click()
        time.sleep(1)  # Give it a sec
        connect_option = waitForElement(driver, By.XPATH, "//div[contains(@class, 'artdeco-dropdown')]//span[contains(text(), 'Connect')]")
        return connect_option
    except:
        logger.error("No connect button found!")
        raise HTTPException(status_code=404, detail="Connect button not found")

def checkIfConnected(driver):
    # Check if we're connected to this profile
    indicators = [
        "//span[contains(text(), '1st')]",
        "//button[contains(text(), 'Message')]",
        "//span[contains(@class, 'connection-status') and contains(text(), 'Connected')]"
    ]
    
    for indicator in indicators:
        try:
            waitForElement(driver, By.XPATH, indicator, timeout=5)
            return True
        except:
            continue
    return False

@app.post("/login")
async def doLogin(creds: LoginCredentials):
    # Login to LinkedIn
    try:
        if not browser_mgr.browser:
            browser_mgr.startBrowser()
        
        browser_mgr.browser.get("https://www.linkedin.com/login")
        browser_mgr.loadCookies()
        
        # Already logged in?
        if "feed" in browser_mgr.browser.current_url:
            logger.info("We're already logged in!")
            return {"status": "ok", "message": "Already logged in"}
        
        # Fill in login form
        username_field = waitForElement(browser_mgr.browser, By.ID, "username")
        username_field.clear()
        username_field.send_keys(creds.email)
        
        password_field = waitForElement(browser_mgr.browser, By.ID, "password")
        password_field.clear()
        password_field.send_keys(creds.passwd)
        
        submit_btn = waitForElement(browser_mgr.browser, By.XPATH, "//button[@type='submit']")
        submit_btn.click()
        
        # Wait for dashboard
        WebDriverWait(browser_mgr.browser, 15).until(
            EC.url_contains("feed")
        )
        
        browser_mgr.saveCookies()
        logger.info(f"Logged in as {creds.email}")
        return {"status": "ok", "message": "Logged in successfully"}
    
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Login didn't work, check credentials")

@app.post("/connect")
async def sendConnect(request: ConnectProfile):
    # Send a connection request
    try:
        if not browser_mgr.browser:
            raise HTTPException(status_code=400, detail="Need to login first!")
        
        browser_mgr.browser.get(request.profileLink)
        connect_button = findConnectBtn(browser_mgr.browser)
        
        # Click with some flair
        actions = ActionChains(browser_mgr.browser)
        actions.move_to_element(connect_button).click().perform()
        
        # Handle any confirmation pop-up
        try:
            send_btn = waitForElement(browser_mgr.browser, By.XPATH, "//button[contains(@aria-label, 'Send now')]", timeout=5)
            send_btn.click()
        except:
            pass  # Sometimes no confirmation needed
        
        browser_mgr.saveCookies()
        logger.info(f"Sent connection request to {request.profileLink}")
        return {"status": "ok", "message": "Connection request sent"}
    
    except Exception as e:
        logger.error(f"Failed to connect: {str(e)}")
        raise HTTPException(status_code=400, detail="Couldn't send connection request")

@app.post("/check_connection")
async def checkAndMessage(request: SendMessage):
    # Check connection and send message
    try:
        if not browser_mgr.browser:
            raise HTTPException(status_code=400, detail="Login required!")
        
        browser_mgr.browser.get(request.profileLink)
        
        if checkIfConnected(browser_mgr.browser):
            message_btn = waitForElement(browser_mgr.browser, By.XPATH, "//button[contains(text(), 'Message')]")
            ActionChains(browser_mgr.browser).move_to_element(message_btn).click().perform()
            
            message_box = waitForElement(browser_mgr.browser, By.XPATH, "//div[@role='textbox']")
            message_box.send_keys(request.messageText)
            
            send_btn = waitForElement(browser_mgr.browser, By.XPATH, "//button[contains(text(), 'Send')]")
            send_btn.click()
            
            logger.info(f"Sent message to {request.profileLink}")
            return {"status": "ok", "message": "Message sent successfully"}
        else:
            logger.info(f"Not connected to {request.profileLink}")
            return {"status": "ok", "message": "Not connected yet"}
    
    except Exception as e:
        logger.error(f"Message sending failed: {str(e)}")
        raise HTTPException(status_code=400, detail="Something went wrong with messaging")

@app.get("/close")
async def closeBrowser():
    # Shut down the browser
    try:
        browser_mgr.shutdown()
        logger.info("All closed up!")
        return {"status": "ok", "message": "Browser session closed"}
    except Exception as e:
        logger.error(f"Shutdown failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Couldn't close the browser")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)