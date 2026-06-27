import os
import sys
import time
import configparser
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException

def super_click(by, value, timeout=20, retries=3):
    """超级点击：综合多种策略，确保点击成功"""
    for attempt in range(retries):
        try:
            element = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
            wait_for_shade_to_disappear()
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
            time.sleep(0.5)
            try:
                element.click()
                log(f"点击成功 (普通) : {value}")
                return
            except ElementClickInterceptedException:
                try:
                    ActionChains(driver).move_to_element(element).click().perform()
                    log(f"点击成功 (ActionChains) : {value}")
                    return
                except:
                    driver.execute_script("arguments[0].click();", element)
                    log(f"点击成功 (JS) : {value}")
                    return
        except (ElementClickInterceptedException, StaleElementReferenceException) as e:
            log(f"点击尝试 {attempt+1}/{retries} 失败: {e}")
            time.sleep(1)
            if attempt == retries - 1:
                raise

# ---------- 获取程序所在目录 ----------
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_path()
LOG_FILE = os.path.join(BASE_DIR, "autorun.log")
CONFIG_FILE = os.path.join(BASE_DIR, "autorun_config.ini")

def log(message):
    text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(text)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except:
        pass

def load_config():
    if not os.path.exists(CONFIG_FILE):
        log(f"错误：配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding="utf-8")
    required_keys = [
        "chrome_binary_path", "use_webdriver_manager", "chromedriver_path",
        "username", "password", "start_url", "ids"
    ]
    cfg = {}
    for key in required_keys:
        if key not in config["DEFAULT"]:
            log(f"错误：配置文件缺少必要项 [{key}]")
            sys.exit(1)
        cfg[key] = config["DEFAULT"][key].strip()
    id_list = [item.strip() for item in cfg["ids"].split(",") if item.strip()]
    if not id_list:
        log("错误：编号列表为空")
        sys.exit(1)
    return cfg, id_list

def wait_for_shade_to_disappear(timeout=30):
    """等待所有 layui-layer-shade 遮罩层消失"""
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, "[class*='layui-layer-shade'], [id^='layui-layer-shade']"))
        )
    except:
        pass

def main():
    global driver
    log("脚本启动")
    cfg, id_list = load_config()

    chrome_options = Options()
    if cfg["chrome_binary_path"] and os.path.exists(cfg["chrome_binary_path"]):
        chrome_options.binary_location = cfg["chrome_binary_path"]
    elif cfg["chrome_binary_path"]:
        log(f"警告：指定的 Chrome 路径不存在: {cfg['chrome_binary_path']}，将使用系统默认路径")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--window-size=1920,1080")

    if cfg["use_webdriver_manager"].lower() == "yes":
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            log("使用 webdriver-manager 自动获取 ChromeDriver")
        except ImportError:
            log("错误：未安装 webdriver-manager")
            sys.exit(1)
    else:
        chromedriver_path = cfg["chromedriver_path"]
        if not chromedriver_path or not os.path.exists(chromedriver_path):
            local_driver = os.path.join(BASE_DIR, "chromedriver.exe")
            if os.path.exists(local_driver):
                chromedriver_path = local_driver
            else:
                log("错误：未找到 chromedriver.exe")
                sys.exit(1)
        service = Service(executable_path=chromedriver_path)

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def wait_a_bit():
        time.sleep(0.8)

    # ========== 优化的 DriverWait：只对元组打印日志，不再打印 function ==========
    def DriverWait(locator, timeout=20):
        if isinstance(locator, tuple):
            by_type, selector = locator
            by_name = {
                By.ID: "id", By.NAME: "name", By.XPATH: "xpath",
                By.CSS_SELECTOR: "css selector", By.CLASS_NAME: "class name",
                By.TAG_NAME: "tag name", By.LINK_TEXT: "link text",
                By.PARTIAL_LINK_TEXT: "partial link text"
            }.get(by_type, str(by_type))
            log(f"正在等待元素 [{by_name}]: {selector}")
            return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))
        else:
            # expected_condition 对象，不打印日志避免冗余
            return WebDriverWait(driver, timeout).until(locator)

    try:
        driver.get(cfg["start_url"])
        log(f"已打开页面: {driver.current_url}")
        wait_a_bit()

        # 登录（只传元组）
        username_input = DriverWait((By.ID, "username"))
        username_input.clear()
        wait_a_bit()
        username_input.send_keys(cfg["username"])
        wait_a_bit()

        password_input = DriverWait((By.ID, "password"))
        password_input.clear()
        wait_a_bit()
        password_input.send_keys(cfg["password"])
        wait_a_bit()

        log("等待手动输入验证码并点击登录...")
        input("请手动输入验证码并点击『登录』按钮，完成后按回车键继续...")

        try:
            login_button = DriverWait((By.XPATH, "//*[@id='submit']"), timeout=5)
            login_button.click()
            wait_a_bit()
        except:
            log("未找到登录按钮，可能已手动登录")

        log("登录流程完成，开始处理编号")

        for number in id_list:
            log(f"开始处理编号: {number}")

            driver.switch_to.default_content()
            wait_for_shade_to_disappear()

            first_menu = DriverWait((By.XPATH, "//*[@id='first-menu']/li[2]/a"))
            driver.execute_script("arguments[0].click();", first_menu)
            wait_a_bit()
            wait_for_shade_to_disappear()

            second_menu = DriverWait((By.XPATH, "//*[@id='menu-left']/ul/li/ul/li[1]/a"))
            driver.execute_script("arguments[0].click();", second_menu)
            wait_a_bit()
            wait_for_shade_to_disappear()

            outer_iframe = DriverWait((By.ID, "iframe_010101"))
            driver.switch_to.frame(outer_iframe)
            wait_a_bit()
            inner_iframe = DriverWait((By.ID, "iframe_list_010101"))
            driver.switch_to.frame(inner_iframe)
            wait_a_bit()

            search_box = DriverWait((By.XPATH, "//input[contains(@id,'yqbh') or contains(@name,'yqbh') or contains(@id,'txt')][1]"))
            search_box.clear()
            wait_a_bit()
            search_box.send_keys(number)
            wait_a_bit()
            search_btn = DriverWait((By.XPATH, "//button[contains(@id,'search') or contains(@class,'search')]"))
            search_btn.click()
            wait_a_bit()

            # 点击开放设置（使用精确定位）
            open_setting_xpath = f"//div[@class='dataTables_scrollBody']//a[contains(@class,'btn_upd_new') and @yqbh='{number}' and text()='开放设置']"
            open_setting = DriverWait((By.XPATH, open_setting_xpath), timeout=20)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", open_setting)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", open_setting)
            log(f"点击开放设置: {number}")
            wait_a_bit()

            # # 选择开放方式
            # DriverWait((By.XPATH, "//*[@id='myform']/div[2]/div[1]/div[2]/div[2]/div/div/div[2]/ins")).click()
            # wait_a_bit()

            DriverWait((By.XPATH, "//*[@id='tr_1']/th[1]/div/img")).click()
            wait_a_bit()

            # 新增开放时间
            DriverWait((By.XPATH, "//*[@id='btn_add']")).click()
            wait_a_bit()

            # 切换到弹窗 iframe（条件等待，保持原样）
            driver.switch_to.default_content()
            WebDriverWait(driver, 20).until(
                EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@id, 'layui-layer-iframe')]"))
            )

            # 弹窗内操作
            DriverWait((By.XPATH, "//*[@id='myform']/div[2]/div/div/div[1]/div/div/div[2]")).click()
            wait_a_bit()
            start_date = DriverWait((By.XPATH, "//*[@id='txt_ksrq']"))
            start_date.click()
            wait_a_bit()
            start_date.send_keys("2026-06-11")
            wait_a_bit()
            end_date = DriverWait((By.XPATH, "//*[@id='txt_jsrq']"))
            end_date.send_keys("2026-08-01")
            wait_a_bit()
            DriverWait((By.XPATH, "/html/body/form/div[1]/div[2]/button")).click()
            wait_a_bit()
            wait_for_shade_to_disappear()

            # 回到内层 iframe
            driver.switch_to.default_content()
            outer_iframe = DriverWait((By.ID, "iframe_010101"))
            driver.switch_to.frame(outer_iframe)
            inner_iframe = DriverWait((By.ID, "iframe_list_010101"))
            driver.switch_to.frame(inner_iframe)
            wait_a_bit()

            # 选择审核人
            # DriverWait((By.XPATH, "//*[@id='syjc_div']/div[2]/div[2]/div/div/div[2]")).click()
            # wait_a_bit()

            # 保存
            DriverWait((By.XPATH, "//*[@id='btn_save']")).click()
            log(f"编号处理完毕: {number}")
            wait_a_bit()
            wait_for_shade_to_disappear()

            driver.switch_to.default_content()
            wait_for_shade_to_disappear()

        log("所有编号处理完成")
    except Exception as e:
        log(f"发生错误: {str(e)}")
        import traceback
        log(traceback.format_exc())
        try:
            screenshot_path = os.path.join(BASE_DIR, f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(screenshot_path)
            log(f"错误截图已保存: {screenshot_path}")
        except:
            pass
    finally:
        driver.quit()
        log("浏览器已关闭")

if __name__ == "__main__":
    main()