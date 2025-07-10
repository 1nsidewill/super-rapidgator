import json
import time
import asyncio
import random
from pathlib import Path
from typing import Dict, Any, Optional
import os

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError
from playwright_stealth import Stealth
from loguru import logger

from ..core.config import settings


class RapidgatorSession:
    """Rapidgator 세션 관리 클래스"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.session_cookies: Dict[str, Any] = {}
        self.session_file = Path("session_cookies.json")
        self.is_logged_in = False
        self.login_time: Optional[float] = None
        self.max_retries = 3
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def initialize_browser(self) -> None:
        """Playwright 브라우저 인스턴스 초기화"""
        try:
            playwright = await async_playwright().start()
            
            # 브라우저 실행 (개발환경에서는 headless=False로 디버깅 가능)
            self.browser = await playwright.chromium.launch(
                headless=settings.browser_headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-extensions',
                    '--no-first-run',
                    '--disable-default-apps',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            # 브라우저 컨텍스트 생성 (쿠키 및 세션 관리)
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            # 기존 세션 쿠키 로드
            await self.load_session_cookies()
            
            # 페이지 생성
            self.page = await self.context.new_page()
            
            # Stealth 모드 활성화 (봇 탐지 회피)
            stealth = Stealth()
            await stealth.apply_stealth_async(self.page)
            
            # 요청/응답 로깅
            self.page.on("response", self._on_response)
            
            logger.info("Playwright 브라우저 인스턴스 초기화 완료")
            
        except Exception as e:
            logger.error(f"브라우저 초기화 실패: {e}")
            await self.close()
            raise
    
    async def _simulate_human_behavior(self) -> None:
        """인간과 유사한 상호작용 시뮬레이션"""
        try:
            # 랜덤한 마우스 움직임
            x = random.randint(100, 500)
            y = random.randint(100, 500)
            await self.page.mouse.move(x, y)
            
            # 랜덤한 지연
            await asyncio.sleep(random.uniform(0.5, 2.0))
            
            # 페이지 스크롤
            await self.page.evaluate('window.scrollBy(0, Math.random() * 200)')
            
            # 짧은 대기
            await asyncio.sleep(random.uniform(0.3, 1.0))
            
        except Exception as e:
            logger.warning(f"Human behavior simulation failed: {e}")
    
    async def login(self, username: str = None, password: str = None) -> bool:
        """Rapidgator 로그인 수행"""
        try:
            # 환경변수에서 크레덴셜 가져오기
            username = username or settings.rapidgator_username
            password = password or settings.rapidgator_password
            
            if not username or not password:
                logger.error("Rapidgator 로그인 정보가 설정되지 않음")
                return False
            
            logger.info("Rapidgator 로그인 시작...")
            
            # 로그인 페이지로 이동
            response = await self.page.goto(
                settings.rapidgator_login_url, 
                wait_until='networkidle',
                timeout=settings.browser_timeout
            )
            
            if not response or response.status != 200:
                logger.error(f"로그인 페이지 로드 실패: {response.status if response else 'No response'}")
                return False
            
            logger.info("로그인 페이지 로드 완료")
            
            # 인간 행동 시뮬레이션
            await self._simulate_human_behavior()
            
            # CSRF 토큰 추출 (여러 가능한 selector 시도)
            csrf_token = None
            csrf_selectors = [
                'input[name="csrf_token"]',
                'input[name="_token"]', 
                'input[name="authenticity_token"]',
                'meta[name="csrf-token"]'
            ]
            
            for selector in csrf_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        if selector.startswith('meta'):
                            csrf_token = await element.get_attribute('content')
                        else:
                            csrf_token = await element.get_attribute('value')
                        if csrf_token:
                            logger.info(f"CSRF 토큰 발견: {selector}")
                            break
                except Exception:
                    continue
            
            if not csrf_token:
                logger.warning("CSRF 토큰을 찾을 수 없음 - 계속 진행")
            
            # 디버깅: 페이지의 모든 input 요소들 찾기
            if settings.debug:
                try:
                    all_inputs = await self.page.query_selector_all('input')
                    logger.info(f"페이지에서 발견된 모든 input 요소들 ({len(all_inputs)}개):")
                    for i, input_element in enumerate(all_inputs):
                        name = await input_element.get_attribute('name') or 'N/A'
                        input_type = await input_element.get_attribute('type') or 'N/A'
                        input_id = await input_element.get_attribute('id') or 'N/A'
                        placeholder = await input_element.get_attribute('placeholder') or 'N/A'
                        css_class = await input_element.get_attribute('class') or 'N/A'
                        is_visible = await input_element.is_visible()
                        logger.info(f"  [{i}] name='{name}', type='{input_type}', id='{input_id}', placeholder='{placeholder}', class='{css_class}', visible={is_visible}")
                except Exception as e:
                    logger.warning(f"디버깅 input 조사 실패: {e}")
                
                # form 요소들도 확인
                try:
                    all_forms = await self.page.query_selector_all('form')
                    logger.info(f"페이지에서 발견된 모든 form 요소들 ({len(all_forms)}개):")
                    for i, form_element in enumerate(all_forms):
                        action = await form_element.get_attribute('action') or 'N/A'
                        method = await form_element.get_attribute('method') or 'N/A'
                        form_id = await form_element.get_attribute('id') or 'N/A'
                        css_class = await form_element.get_attribute('class') or 'N/A'
                        logger.info(f"  [{i}] action='{action}', method='{method}', id='{form_id}', class='{css_class}'")
                except Exception as e:
                    logger.warning(f"디버깅 form 조사 실패: {e}")
            
            # 로그인 폼 selector들
            login_selectors = {
                'username': [
                    # Rapidgator 실제 선택자들 (디버깅으로 확인됨)
                    'input[name="LoginForm[email]"]',
                    '#LoginForm_email',
                    '.main-login[type="text"]',
                    # 일반적인 fallback 선택자들
                    'input[name="username"]',
                    'input[name="login"]', 
                    'input[name="email"]',
                    'input[type="email"]',
                    '#username',
                    '#login',
                    '#email'
                ],
                'password': [
                    # Rapidgator 실제 선택자들
                    'input[name="LoginForm[password]"]',
                    '#LoginForm_password',
                    '.main-login[type="password"]',
                    # 일반적인 fallback 선택자들
                    'input[name="password"]',
                    'input[type="password"]',
                    '#password'
                ],
                'submit': [
                    # Rapidgator 실제 form 구조에 맞는 선택자들
                    '#registration button[type="submit"]',
                    '#registration input[type="submit"]',
                    'form[action="/auth/login"] button[type="submit"]',
                    'form[action="/auth/login"] input[type="submit"]',
                    # 일반적인 fallback 선택자들
                    'button[type="submit"]',
                    'input[type="submit"]',
                    '.login-btn',
                    '#login-btn',
                    'button:has-text("Login")',
                    'button:has-text("Sign in")'
                ]
            }
            
            # 사용자명 입력
            username_filled = False
            for selector in login_selectors['username']:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        await self._simulate_human_behavior()
                        await element.fill("")  # clear() 대신 fill("") 사용
                        await element.type(username, delay=random.randint(50, 150))
                        logger.info(f"사용자명 입력 완료: {selector}")
                        username_filled = True
                        break
                except Exception as e:
                    logger.debug(f"Username selector {selector} failed: {e}")
                    continue
            
            if not username_filled:
                logger.error("사용자명 입력 필드를 찾을 수 없음")
                return False
            
            # 패스워드 입력
            password_filled = False
            for selector in login_selectors['password']:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        await self._simulate_human_behavior()
                        await element.fill("")  # clear() 대신 fill("") 사용
                        await element.type(password, delay=random.randint(50, 150))
                        logger.info(f"패스워드 입력 완료: {selector}")
                        password_filled = True
                        break
                except Exception as e:
                    logger.debug(f"Password selector {selector} failed: {e}")
                    continue
            
            if not password_filled:
                logger.error("패스워드 입력 필드를 찾을 수 없음")
                return False
            
            # 디버깅: 페이지의 모든 button과 submit 요소들 찾기
            if settings.debug:
                try:
                    all_buttons = await self.page.query_selector_all('button')
                    logger.info(f"페이지에서 발견된 모든 button 요소들 ({len(all_buttons)}개):")
                    for i, button_element in enumerate(all_buttons):
                        button_type = await button_element.get_attribute('type') or 'N/A'
                        button_id = await button_element.get_attribute('id') or 'N/A'
                        button_class = await button_element.get_attribute('class') or 'N/A'
                        button_text = await button_element.text_content() or 'N/A'
                        is_visible = await button_element.is_visible()
                        logger.info(f"  [{i}] type='{button_type}', id='{button_id}', class='{button_class}', text='{button_text}', visible={is_visible}")
                except Exception as e:
                    logger.warning(f"디버깅 button 조사 실패: {e}")
                
                try:
                    all_submits = await self.page.query_selector_all('input[type="submit"]')
                    logger.info(f"페이지에서 발견된 모든 submit input 요소들 ({len(all_submits)}개):")
                    for i, submit_element in enumerate(all_submits):
                        submit_value = await submit_element.get_attribute('value') or 'N/A'
                        submit_id = await submit_element.get_attribute('id') or 'N/A'
                        submit_class = await submit_element.get_attribute('class') or 'N/A'
                        is_visible = await submit_element.is_visible()
                        logger.info(f"  [{i}] value='{submit_value}', id='{submit_id}', class='{submit_class}', visible={is_visible}")
                except Exception as e:
                    logger.warning(f"디버깅 submit 조사 실패: {e}")
                
                # 포괄적인 클릭 가능한 요소들 찾기
                try:
                    clickable_selectors = [
                        'a',  # 링크
                        '[onclick]',  # onclick 이벤트 있는 요소들
                        '[role="button"]',  # button 역할의 요소들
                        '.btn',  # btn 클래스
                        '.button',  # button 클래스
                        '.submit',  # submit 클래스
                        '.login',  # login 클래스
                        '[type="button"]',  # button 타입
                        'span[onclick]',  # 클릭 가능한 span
                        'div[onclick]',  # 클릭 가능한 div
                    ]
                    
                    for selector in clickable_selectors:
                        elements = await self.page.query_selector_all(selector)
                        if elements:
                            logger.info(f"'{selector}' 선택자로 발견된 요소들 ({len(elements)}개):")
                            for i, element in enumerate(elements):
                                try:
                                    tag_name = await element.evaluate('el => el.tagName') or 'N/A'
                                    element_id = await element.get_attribute('id') or 'N/A'
                                    element_class = await element.get_attribute('class') or 'N/A'
                                    element_text = await element.text_content() or 'N/A'
                                    onclick = await element.get_attribute('onclick') or 'N/A'
                                    is_visible = await element.is_visible()
                                    logger.info(f"  [{i}] tag='{tag_name}', id='{element_id}', class='{element_class}', text='{element_text[:50]}', onclick='{onclick[:50]}', visible={is_visible}")
                                except Exception as element_error:
                                    logger.debug(f"Element {i} analysis failed: {element_error}")
                except Exception as e:
                    logger.warning(f"디버깅 클릭 가능한 요소 조사 실패: {e}")
            
            # CSRF 토큰 입력 (있는 경우)
            if csrf_token:
                for selector in csrf_selectors:
                    if not selector.startswith('meta'):
                        try:
                            element = await self.page.query_selector(selector)
                            if element:
                                await element.fill(csrf_token)
                                logger.info("CSRF 토큰 입력 완료")
                                break
                        except Exception:
                            continue
            
            # 로그인 버튼 클릭
            submit_selectors = [
                # Rapidgator 실제 로그인 버튼 (디버깅으로 확인됨)
                'a.btn.send-message',  # class가 'btn send-message'인 a 태그
                "a[onclick*='registration.submit']",  # onclick에 registration.submit이 포함된 a 태그
                "a[class*='btn'][class*='send-message']",  # 클래스에 btn과 send-message가 포함된 a 태그
                # 일반적인 fallback 선택자들
                'button[type="submit"]',
                'input[type="submit"]',
                'button:contains("Login")',
                'button:contains("Enter")',
                '.submit-btn',
                '.login-btn',
                '#submit',
                '#login-submit'
            ]
            
            login_clicked = False
            for selector in submit_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        await element.click()
                        logger.info(f"로그인 버튼 클릭: {selector}")
                        login_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"Submit selector {selector} failed: {e}")
                    continue
            
            if not login_clicked:
                logger.error("로그인 버튼을 찾을 수 없음")
                return False
            
            # 로그인 결과 대기
            try:
                await self.page.wait_for_load_state('networkidle', timeout=30000)
            except Exception as e:
                logger.warning(f"Network idle 대기 실패: {e}")
            
            # 로그인 성공 확인
            current_url = self.page.url
            logger.info(f"로그인 후 URL: {current_url}")
            
            # 로그인 실패 감지 (로그인 페이지에 그대로 있거나 에러 메시지)
            if 'login' in current_url or 'auth' in current_url:
                # 에러 메시지 확인
                error_selectors = [
                    '.error',
                    '.alert-danger',
                    '.alert-error',
                    '[class*="error"]',
                    '[class*="invalid"]'
                ]
                
                for selector in error_selectors:
                    try:
                        error_element = await self.page.query_selector(selector)
                        if error_element and await error_element.is_visible():
                            error_text = await error_element.text_content()
                            logger.error(f"로그인 에러: {error_text}")
                            return False
                    except Exception:
                        continue
                
                logger.error("로그인 실패 - 로그인 페이지에 남아있음")
                return False
            
            # 로그인 성공
            self.is_logged_in = True
            self.login_time = time.time()
            
            # 세션 쿠키 저장
            await self.save_session_cookies()
            
            logger.info("Rapidgator 로그인 성공!")
            return True
            
        except Exception as e:
            logger.error(f"로그인 중 오류 발생: {e}")
            return False
    
    async def _on_response(self, response) -> None:
        """HTTP 응답 로깅"""
        if settings.debug:
            logger.debug(f"Response: {response.status} {response.url}")
    
    async def load_session_cookies(self) -> None:
        """저장된 세션 쿠키 로드"""
        try:
            if self.session_file.exists():
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
                    self.session_cookies = data.get('cookies', {})
                    self.login_time = data.get('login_time')
                    
                    # 컨텍스트에 쿠키 설정
                    if self.session_cookies and self.context:
                        cookies_list = []
                        for name, value in self.session_cookies.items():
                            cookies_list.append({
                                'name': name,
                                'value': value,
                                'domain': '.rapidgator.net',
                                'path': '/'
                            })
                        await self.context.add_cookies(cookies_list)
                        logger.info(f"세션 쿠키 {len(cookies_list)}개 로드됨")
                        
        except Exception as e:
            logger.warning(f"세션 쿠키 로드 실패: {e}")
    
    async def save_session_cookies(self) -> None:
        """현재 세션 쿠키 저장"""
        try:
            if self.context:
                cookies = await self.context.cookies()
                
                # Rapidgator 도메인 쿠키만 필터링
                rg_cookies = {}
                for cookie in cookies:
                    if 'rapidgator' in cookie['domain']:
                        rg_cookies[cookie['name']] = cookie['value']
                
                data = {
                    'cookies': rg_cookies,
                    'login_time': self.login_time or time.time()
                }
                
                with open(self.session_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                self.session_cookies = rg_cookies
                logger.info(f"세션 쿠키 {len(rg_cookies)}개 저장됨")
                
        except Exception as e:
            logger.error(f"세션 쿠키 저장 실패: {e}")
    
    async def is_session_valid(self) -> bool:
        """현재 세션이 유효한지 확인"""
        try:
            if not self.page or not self.session_cookies:
                return False
            
            # 로그인 후 1시간 경과 시 무효 처리
            if self.login_time and (time.time() - self.login_time) > settings.rapidgator_session_timeout:
                logger.info("세션 시간 만료")
                return False
            
            # 실제 로그인 상태 확인 - 메인 페이지에서 로그인 상태 확인
            response = await self.page.goto('https://rapidgator.net/', wait_until='networkidle')
            
            if response and response.status == 200:
                # 페이지 내용에서 로그인 상태 확인
                try:
                    # 로그아웃 링크가 있으면 로그인 상태
                    logout_element = await self.page.query_selector('a[href*="logout"]')
                    if logout_element:
                        self.is_logged_in = True
                        logger.info("기존 세션이 유효함 (로그아웃 링크 확인)")
                        return True
                    
                    # 또는 사용자 계정 관련 요소가 있는지 확인
                    account_elements = await self.page.query_selector_all('a:has-text("My account"), a:has-text("Profile"), a[href*="account"]')
                    if account_elements:
                        self.is_logged_in = True
                        logger.info("기존 세션이 유효함 (계정 메뉴 확인)")
                        return True
                        
                    # 로그인 폼이 없으면 이미 로그인된 상태일 수 있음
                    login_form = await self.page.query_selector('form[action*="login"]')
                    if not login_form:
                        self.is_logged_in = True
                        logger.info("기존 세션이 유효함 (로그인 폼 없음)")
                        return True
                    
                except Exception as e:
                    logger.warning(f"세션 유효성 확인 중 오류: {e}")
            
            self.is_logged_in = False
            return False
            
        except Exception as e:
            logger.error(f"세션 유효성 검사 실패: {e}")
            return False
    
    async def download_file(self, url: str, download_dir: str) -> Dict[str, Any]:
        """Rapidgator에서 파일 다운로드 (프리미엄 계정용)"""
        try:
            if not self.page or self.page.is_closed():
                logger.warning("페이지가 없거나 닫혀있어 새로 생성합니다.")
                self.page = await self.context.new_page()
                await Stealth.apply_stealth_async(self.page)
                self.page.on("response", self._on_response)

            # 1. 다운로드가 시작될 것을 미리 "기대"합니다.
            async with self.page.expect_download(timeout=settings.browser_timeout * 4) as download_info:
                # 2. 페이지로 이동을 시도합니다.
                try:
                    await self.page.goto(
                        url, 
                        wait_until='domcontentloaded', 
                        timeout=settings.browser_timeout * 3
                    )
                    # 3. 페이지 이동 후 버튼 클릭 (이동만으로 다운로드가 안될 경우 대비)
                    download_button = self.page.locator("a.btn-premium").first
                    # Fix: Remove timeout parameter from is_visible() method
                    try:
                        await download_button.wait_for(state='visible', timeout=5000)
                        if await download_button.is_visible():
                         await download_button.click()
                    except Exception as e:
                        logger.debug(f"다운로드 버튼 클릭 실패: {e}")
                    # 버튼이 없어도 페이지 이동만으로 다운로드가 시작될 수 있음
                except PlaywrightError as e:
                    if "net::ERR_ABORTED" in str(e):
                        logger.info("페이지 이동이 중단되었습니다. 다운로드 시작으로 간주합니다 (정상 동작).")
                    else:
                        raise  # 다른 Playwright 오류는 다시 발생시킵니다.

            # 4. 실제 다운로드 객체를 기다립니다.
            download = await download_info.value
            logger.info(f"다운로드 시작됨: {download.suggested_filename}")

            # 다운로드 경로 설정
            sanitized_filename = "".join(c for c in download.suggested_filename if c.isalnum() or c in (' ', '.', '_')).rstrip()
            filepath = Path(download_dir) / sanitized_filename
            
            # 파일 저장
            await download.save_as(filepath)
            
            logger.info(f"파일 다운로드 완료: {filepath}")
            
            # 파일 크기 확인 (파일이 저장된 후)
            try:
                file_size = filepath.stat().st_size
            except Exception as e:
                logger.warning(f"파일 크기 확인 실패: {e}")
                file_size = 0

            return {
                "success": True,
                "filepath": str(filepath),
                "filename": sanitized_filename,
                "file_size": file_size,  # total_bytes 대신 file_size로 변경
            }

        except Exception as e:
            logger.error(f"다운로드 프로세스 실패: {e}")
            return {
                "success": False,
                "error": f"다운로드 실패: {e}",
                "url": url
            }
    
    async def close(self) -> None:
        """브라우저 리소스 정리"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
                
            logger.info("브라우저 리소스 정리 완료")
            
        except Exception as e:
            logger.error(f"브라우저 정리 중 오류: {e}")


class RapidgatorClient:
    """Rapidgator 클라이언트 메인 클래스"""
    
    def __init__(self):
        self.session: Optional[RapidgatorSession] = None
    
    async def get_or_create_session(self) -> RapidgatorSession:
        """세션 가져오기 또는 생성"""
        if not self.session:
            self.session = RapidgatorSession()
            await self.session.initialize_browser()
        
        return self.session
    
    async def login(self, username: str = None, password: str = None) -> bool:
        """로그인 수행"""
        try:
            session = await self.get_or_create_session()
            return await session.login(username, password)
        except Exception as e:
            logger.error(f"클라이언트 로그인 실패: {e}")
            return False
    
    async def ensure_logged_in(self) -> bool:
        """로그인 상태 확인 및 필요시 로그인 수행"""
        session = await self.get_or_create_session()
        
        # 기존 세션 유효성 검사
        if await session.is_session_valid():
            return True
        
        # 로그인 필요
        logger.info("새로운 로그인 필요")
        return await session.login()
    
    async def get_session_status(self) -> Dict[str, Any]:
        """현재 세션 상태 반환"""
        try:
            if not self.session:
                return {
                    "logged_in": False,
                    "session_exists": False,
                    "message": "세션이 생성되지 않음"
                }
            
            is_valid = await self.session.is_session_valid()
            
            return {
                "logged_in": is_valid,
                "session_exists": True,
                "login_time": self.session.login_time,
                "cookies_count": len(self.session.session_cookies),
                "message": "로그인 상태 정상" if is_valid else "로그인 필요"
            }
            
        except Exception as e:
            logger.error(f"세션 상태 확인 실패: {e}")
            return {
                "logged_in": False,
                "session_exists": False,
                "error": str(e),
                "message": "세션 상태 확인 중 오류 발생"
            }
    
    async def logout(self) -> bool:
        """로그아웃 및 세션 정리"""
        try:
            if self.session:
                # 세션 쿠키 파일 삭제
                if self.session.session_file.exists():
                    self.session.session_file.unlink()
                    logger.info("세션 쿠키 파일 삭제됨")
                
                # 브라우저 정리
                await self.session.close()
                self.session = None
                
                logger.info("로그아웃 완료")
                return True
            else:
                logger.info("로그아웃할 세션이 없음")
                return True
                
        except Exception as e:
            logger.error(f"로그아웃 실패: {e}")
            return False
    
    async def close(self) -> None:
        """클라이언트 정리"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def download_file(self, url: str, download_dir: str) -> Dict[str, Any]:
        """파일 다운로드 수행"""
        try:
            # 로그인 상태 확인
            if not await self.ensure_logged_in():
                return {
                    "success": False,
                    "error": "로그인이 필요합니다"
                }
            
            session = await self.get_or_create_session()
            return await session.download_file(url, download_dir)
            
        except Exception as e:
            logger.error(f"다운로드 실패: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def initialize_browser(self) -> None:
        """브라우저 초기화 (호환성을 위한 메소드)"""
        session = await self.get_or_create_session()
        # 세션이 이미 초기화됨 


# 전역 클라이언트 인스턴스
rapidgator_client = RapidgatorClient() 