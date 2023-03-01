import json
import os
import random
import re
import sys
import threading
from pathlib import Path
from queue import Queue
import pyautogui
from django.utils import timezone

from time import sleep
from selenium import webdriver
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from undetected_chromedriver import Chrome, ChromeOptions

if __name__ == '__main__':
    import django

    # sys.path.append(os.path.dirname(os.path.abspath('.')))
    path = Path(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(str(path.parent.parent))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'web.settings'
    django.setup()

from app.models import *
from scraper.constants import *


class Crawler(threading.Thread):
    def __init__(self, **kwargs):
        super().__init__()

        self.queue = Queue()
        self.url = None
        self.payload = None
        self.store = None
        self.size = None

        for key, value in kwargs.items():
            self.__setattr__(key, value)

    def run(self):

        self.driver = self.new_driver(browser=CHROME)
        self.block_requests()
        self.add_cookies()

        # self.driver = self.new_driver(browser=FIREFOX)
        # self.login()

        self.driver.set_page_load_timeout(15)

        while True:

            try:
                self.payload = self.queue.get(block=False)
            except:
                sleep(1)
                continue

            self.x = self.payload['x']
            self.url = f"https://www.starbucks.com/menu{self.x.uri}"
            self.store = self.payload['store']
            self.size = self.payload['size']

            try:
                self.driver.get(self.url)
            except TimeoutException:
                self.queue.put(self.payload)
                continue
            except Exception as e:
                print(e)
                continue
            sleep(3)

            self.parse_product_page()

            sleep(random.uniform(3, 8))

    def new_payload(self):

        payload = {
            'cats': '',
            'url': None,
        }
        return payload

    def parse_product_page(self):

        while True:
            store_is_set = len(
                self.driver.find_elements('xpath',
                                          "//p[contains(text(),'For item availability, choose a store')]")) == 0

            if not store_is_set:
                self.change_store(self.store)
                self.driver.get(self.url)
            else:
                break

        # TODO Bekleme süresini azaltmak için ürünün size ına bakılıp size seçenekleri ona göre beklenebilir
        try:
            WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(
                (By.XPATH, "//input[@name='size'] | //select[@id='sizeSelector']")))
        except:
            pass

        try:
            WebDriverWait(self.driver, 3).until(EC.presence_of_element_located(
                (By.XPATH, "//button[@data-e2e='add-to-order-button']")))
        except:
            pass

        product_added = False

        try:
            product_unavailable = self.driver.find_element('xpath',
                                                           "//*[@data-e2e='product-unavailable-message']").text.strip()
        except:
            product_unavailable = None

        add_to_order_btn = self.driver.find_element('xpath', "//button[@data-e2e='add-to-order-button']")

        # ---------------- Side by Side Sizes -------------------------

        size_elems = self.driver.find_elements('xpath', "//input[@name='size']")

        for n, elem in enumerate(size_elems):

            size = elem.get_attribute('id').strip()

            p = get_price_obj(self.x, self.store, size)

            if not p:
                p = Price.objects.create(
                    product=self.x,
                    store=self.store,
                    size=size,
                )

            if not p.volume:
                p.volume = elem.find_element('xpath', "./following-sibling::p[last()]").text.strip()
                p.cache_time = timezone.now()
                p.save()

            if product_unavailable:
                p.price = product_unavailable
                p.cache_time = timezone.now()
                p.save()

            if not p.price:
                self.driver.execute_script("arguments[0].click();", elem)

                WebDriverWait(elem, 5).until(EC.presence_of_element_located(
                    (By.XPATH, "./ancestor::*[2][contains(@class,'active')]")))

                add_to_order_btn.click()
                sleep(random.uniform(1, 3))

                product_added = True

        # ---------------- Drop Down Sizes -------------------------

        if not size_elems:

            size_elems = self.driver.find_elements('xpath', "//select[@id='sizeSelector']/option[not(@disabled)]")

            if size_elems:

                try:
                    size_selector = Select(
                        self.driver.find_element('xpath', "//select[@id='sizeSelector']"))
                except:
                    print('ERROR:', self.store.url, self.url)

                for n, elem in enumerate(size_elems):

                    size = elem.get_attribute('value').strip()

                    p = get_price_obj(self.x, self.store, size)

                    if not p:
                        p = Price.objects.create(
                            product=self.x,
                            store=self.store,
                            size=size,
                        )

                    if not p.volume:
                        p.volume = elem.text.strip()
                        p.volume = re.sub(size, '', p.volume, flags=re.I).strip()
                        p.save()

                    if product_unavailable:
                        p.price = product_unavailable
                        p.cache_time = timezone.now()
                        p.save()

                    if not p.price:
                        size_selector.select_by_value(size)
                        sleep(2)

                        add_to_order_btn.click()
                        sleep(random.uniform(1, 3))

                        product_added = True

            else:
                try:
                    x_sizes = self.x.sizes.split(' | ')
                except:
                    x_sizes = []

                if product_unavailable and len(x_sizes) == 1:

                    size = self.x.sizes

                    p = get_price_obj(self.x, store, size)

                    if p:
                        p.price = product_unavailable
                        p.cache_time = timezone.now()
                        p.save()
                    else:
                        Price.objects.create(
                            product=self.x,
                            store=self.store,
                            size=size,
                            price=product_unavailable,
                            cache_time=timezone.now(),
                        )
                else:
                    add_to_order_btn.click()
                    sleep(random.uniform(1, 3))

                    product_added = True

        if product_added:
            for _ in range(2):
                if self.get_prices_from_cart():
                    break
                elif _ == 0:
                    self.driver.refresh()
                    sleep(1)
                    try:
                        add_to_order_btn = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
                            (By.XPATH, "//button[@data-e2e='add-to-order-button']")))
                        add_to_order_btn.click()
                        sleep(2)
                    except:
                        pass

        # if product_added:
        #     for _ in range(2):
        #         if self.get_prices_from_cart():
        #             break
        #         elif _ == 0:
        #             self.driver.refresh()
        #             sleep(1)
        #             try:
        #                 add_to_order_btn = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
        #                     (By.XPATH, "//button[@data-e2e='add-to-order-button']")))
        #                 add_to_order_btn.click()
        #                 sleep(2)
        #             except:
        #                 pass
    def check_login(self):

        signed_out = len(self.driver.find_elements('xpath', "//button[@data-e2e='signInButton']")) > 0

        if signed_out:
            main_window = self.driver.current_window_handle

            self.login()

    def get_prices_from_cart(self):

        main_window = self.driver.current_window_handle

        self.driver.execute_script(f'window.open("https://www.starbucks.com/menu/cart","_blank");')
        sleep(2)
        self.driver.switch_to.window(self.driver.window_handles[-1])
        sleep(1)

        store_is_set = len(
            self.driver.find_elements('xpath', "//p[contains(text(),'For item availability, choose a store')]")) == 0

        if not store_is_set:
            self.change_store(self.store)
            self.driver.get("https://www.starbucks.com/menu/cart")

        empty_cart = len(self.driver.find_elements('xpath', "//*[@data-e2e='empty-cart']")) > 0
        if empty_cart:
            self.driver.close()
            self.driver.switch_to.window(main_window)
            return False

        for _ in range(1):
            if empty_cart:
                break
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, "//*[@data-e2e='cart-item-price']")))
                break
            except:
                try:
                    WebDriverWait(self.driver, 1).until(EC.presence_of_element_located(
                        (By.XPATH,
                         "//span[contains(text(),'Not sold at this store')] | //span[contains(text(),'Sold out at this store')]")))
                    break
                except:
                    # self.driver.refresh()
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                    self.driver.execute_script(f'window.open("https://www.starbucks.com/menu/cart","_blank");')
                    sleep(2)
                    self.driver.switch_to.window(self.driver.window_handles[-1])
                    sleep(1)
        else:
            print()

        # --------------------- Save Prices ---------------------

        elems = self.driver.find_elements('xpath', "//*[@data-e2e='cart-item']")

        for elem in elems:

            name = elem.find_element('xpath', ".//h3[@data-e2e='heading']").text.strip()
            try:
                price = elem.find_element('xpath', ".//*[@data-e2e='cart-item-price']").text.strip()
            except:
                try:
                    price = elem.find_element('xpath',
                                              ".//span[contains(text(),'Not sold at this store')] | //span[contains(text(),'Sold out at this store')]").text.strip()
                except:
                    price = None
                    continue

            try:
                size_volume = elem.find_element('xpath', ".//*[@data-e2e='option-price-line']/p").text.strip()
                size = size_volume.split(maxsplit=1)[0]
                try:
                    volume = size_volume.split(maxsplit=1)[1]
                except:
                    volume = None
            except:
                size = volume = None

            p = get_price_obj(self.x, self.store, size, name)

            if not p:
                p = Price.objects.create(
                    product=self.x,
                    store=self.store,
                    size=size,
                    volume=volume,
                )

            # if name == self.x.name and size == p.size \
            #         or (size in ['Single', 'Solo'] and p.size in ['Single', 'Solo']) \
            #         or (size in ['Double', 'Doppio'] and p.size in ['Double', 'Doppio']):
            if not p.volume and volume:
                p.volume = volume
            p.price = price
            p.cache_time = timezone.now()
            p.save()

        # ------------------- Remove Items from Cart ---------------------------

        while len(elems) > 0:

            sleep(random.uniform(1, 2))

            remove_btn = elems[-1].find_element('xpath', ".//button[@data-e2e='decreaseQuantityButton']")
            try:
                self.driver.execute_script("arguments[0].click();", remove_btn)
            except StaleElementReferenceException:
                self.driver.refresh()
                sleep(3)
            except:
                pass
            sleep(0.5)
            elems = self.driver.find_elements('xpath', "//*[@data-e2e='cart-item']")

        self.driver.close()
        self.driver.switch_to.window(main_window)

        return True

    def add_cookies(self):
        self.driver.get('https://www.starbucks.com')

        cookies = json.load(open('cookies.json'))
        for cookie in cookies:
            if cookie:
                self.driver.add_cookie({'name': cookie['name'], 'value': cookie['value'], 'domain': cookie['domain']})

    def block_requests(self):

        self.driver.execute_cdp_cmd('Network.setBlockedURLs', {"urls": [
            '*bam.nr-data.net*',
        ]})
        self.driver.execute_cdp_cmd('Network.enable', {})

    def new_driver(self, browser=None):

        if browser == FIREFOX:
            return self.new_firefox_driver()
        else:
            return self.new_chrome_driver()


    def new_firefox_driver(self):

        firefox_driver_path = f'{os.getcwd()}/drivers/geckodriver.exe'
        firefox_binary_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        firefox_binary = FirefoxBinary(firefox_binary_path)
        firefox_options = webdriver.FirefoxOptions()
        firefox_options.binary = firefox_binary
        driver = webdriver.Firefox(executable_path=firefox_driver_path, options=firefox_options)
        driver.set_window_size(960, 1040)
        driver.set_window_position(960, 0)
        return driver

    def new_chrome_driver(self):

        options = ChromeOptions()
        # options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-first-run --no-service-autorun --password-store=basic')
        options.add_argument('--disable-popup-blocking')

        options.add_argument(f'--window-position=960,0')
        options.add_argument("--window-size=960,1040")

        driver = Chrome(options=options)

        driver.set_window_size(960, 1040)
        driver.set_window_position(960, 0)
        driver.execute_script("document.body.style.zoom='90%'")

        return driver

    def change_store(self, store):

        self.driver.get(store.url)

        order_here_btn = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located(
            (By.XPATH, "//div[contains(@class,'sb-animator-fadeGrow-appear-done')]/button[@data-e2e='confirmStoreButton']")))

        order_here_btn.click()

        sleep(3)

    def login_v1(self):

        username = 'neccen@hotmail.com'
        password = 'Neccen1453*-+'

        self.driver.get('https://www.starbucks.com/account/signin')

        # Find the username field
        try:
            pyautogui.click('images/agree_button.png')
            sleep(2)
        except:
            pass

        pyautogui.click('images/username_field.png')
        pyautogui.write(username, interval=0.2)

        # Find the password field
        password_field = pyautogui.locateOnScreen('images/password_field.png')
        if password_field is None:
            print("Error: Could not find the password field.")
            exit()

        # Click on the password field and type the password
        password_pos = pyautogui.center(password_field)
        pyautogui.click(password_pos)
        pyautogui.write(password, interval=0.2)

        # Find the sign-in button
        signin_button = pyautogui.locateOnScreen('images/signin_button.png')
        if signin_button is None:
            print("Error: Could not find the sign-in button.")
            exit()

        # Click on the sign-in button
        signin_pos = pyautogui.center(signin_button)
        pyautogui.click(signin_pos)

        print()

    def login(self, new_tab=True):

        username = 'neccen@hotmail.com'
        password = 'Neccen1453*-+'

        logged_in = len(self.driver.find_elements('xpath', "//div/button[@data-e2e='accountHamburgerNavPushViewBtn']")) > 0

        while not logged_in:

            if new_tab:

                main_window = self.driver.current_window_handle

                self.driver.execute_script(f'window.open("https://www.starbucks.com/account/signin","_blank");')
                sleep(2)
                self.driver.switch_to.window(self.driver.window_handles[-1])
                sleep(1)

            else:
                self.driver.get('https://www.starbucks.com/account/signin')

            actions = ActionChains(self.driver)

            try:
                agree_btn = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, "//button[@id='truste-consent-button']")))
                actions.move_to_element(agree_btn).click().perform()
                sleep(1)
            except:
                pass

            email_input = self.driver.find_element('name', 'username')
            actions.move_to_element(email_input).click().perform()
            sleep(1)
            # email_input.send_keys(username)
            for char in username:
                pause = random.uniform(0.2, 0.6)
                actions.send_keys(char).pause(pause)
            actions.perform()

            # Perform the actions

            sleep(2)

            pwd_input = self.driver.find_element('name', 'password')
            actions.move_to_element(pwd_input).click().perform()
            sleep(1)
            # pwd_input.send_keys(password)
            for char in password:
                pause = random.uniform(0.2, 0.6)
                actions.send_keys(char).pause(pause)
            actions.perform()

            sleep(2)

            signin_btn = self.driver.find_element('xpath', "//button[@type='submit']")
            actions.move_to_element(signin_btn).click().perform()

            sleep(3)

            try:
                account_btn = WebDriverWait(self.driver, 7).until(EC.presence_of_element_located(
                    (By.XPATH, "//div/button[@data-e2e='accountHamburgerNavPushViewBtn']")))
                self.driver.close()
                sleep(1)
                self.driver.switch_to.window(main_window)
                sleep(1)
                break
            except:
                if new_tab:
                    self.driver.close()
                    sleep(1)
                    self.driver.switch_to.window(main_window)
                    sleep(1)


def get_price_obj(x, store, size, name=None):

    x_sizes = x.sizes.split(' | ')

    if size in ['Single', 'Solo']:
        p = x.prices.filter(size__in=['Single', 'Solo'], store=store).first() or None
    elif size in ['Double', 'Doppio']:
        p = x.prices.filter(size__in=['Double', 'Doppio'], store=store).first() or None
    else:
        if len(x_sizes) == 1:
            p = x.prices.filter(store=store).first() or None
        else:
            p = x.prices.filter(size__iexact=size, store=store).first() or None

    if not size or not p or (p and not p.size):

        if not p:
            p = Price.objects.create(
                product=x,
                store=store,
                size=size,
                )
        elif not p.size:
            p.size = x_sizes[0]
            p.save()
        else:
            print()
    else:
        print()

    return p


if __name__ == '__main__':

    queue = Queue()

    stores = Store.objects.filter(id=2)
    qs = Product.objects.all()
    loaded_products = set()

    for store in stores:

        for x in qs:

            try:
                sizes = x.sizes.split(' | ')
            except:
                sizes = None

            if sizes:
                for size in sizes:

                    p = get_price_obj(x, store, size)

                    if not p or not p.price:
                        payload = {
                            'x': x,
                            'size': size,
                            'store': store,
                        }
                        queue.put(payload)
                        break
            else:
                p = x.prices.filter(store=store, price__isnull=True).first() or None
                payload = {
                    'x': x,
                    'size': None,
                    'store': store,
                }
                queue.put(payload)

    kwargs = {
        'queue': queue,
    }
    qsize = queue.qsize()

    threads = list()

    for i in range(1):
        t = Crawler(**kwargs)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
