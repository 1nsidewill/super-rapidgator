from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from ..services.rapidgator_client import rapidgator_client
from loguru import logger

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


class LoginResponse(BaseModel):
    success: bool
    message: str
    session_info: Optional[dict] = None


class SessionStatusResponse(BaseModel):
    logged_in: bool
    session_exists: bool
    login_time: Optional[float] = None
    cookies_count: Optional[int] = None
    message: str
    error: Optional[str] = None


# 웹 UI 호환성을 위한 표준 경로들
@router.get("/status", response_model=SessionStatusResponse)
async def get_auth_status():
    """
    현재 인증 상태 확인 (웹 UI용)
    """
    return await get_rapidgator_status()


@router.post("/login", response_model=LoginResponse)
async def auth_login(request: LoginRequest):
    """
    로그인 수행 (웹 UI용)
    """
    return await login_rapidgator(request)


@router.post("/logout")
async def auth_logout():
    """
    로그아웃 수행 (웹 UI용)
    """
    return await logout_rapidgator()


@router.post("/refresh")
async def auth_refresh():
    """
    세션 갱신 (웹 UI용)
    """
    try:
        logger.info("세션 갱신 요청")
        
        # 기존 세션 유효성 확인 후 필요시 재로그인
        success = await rapidgator_client.ensure_logged_in()
        
        if success:
            session_status = await rapidgator_client.get_session_status()
            return {
                "success": True,
                "message": "세션이 갱신되었습니다",
                "session_info": session_status
            }
        else:
            return {
                "success": False,
                "message": "세션 갱신 실패 - 다시 로그인해주세요"
            }
            
    except Exception as e:
        logger.error(f"세션 갱신 API 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"세션 갱신 중 오류가 발생했습니다: {str(e)}"
        )


# 기존 Rapidgator 전용 경로들
@router.post("/rapidgator/login", response_model=LoginResponse)
async def login_rapidgator(request: LoginRequest):
    """
    Rapidgator 로그인 수행
    """
    try:
        logger.info("Rapidgator 로그인 요청 받음")
        
        # 로그인 수행
        success = await rapidgator_client.login(
            username=request.username,
            password=request.password
        )
        
        if success:
            # 세션 상태 가져오기
            session_status = await rapidgator_client.get_session_status()
            
            return LoginResponse(
                success=True,
                message="Rapidgator 로그인 성공",
                session_info=session_status
            )
        else:
            return LoginResponse(
                success=False,
                message="Rapidgator 로그인 실패 - 자격 증명을 확인해주세요"
            )
            
    except Exception as e:
        logger.error(f"로그인 API 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"로그인 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/rapidgator/status", response_model=SessionStatusResponse)
async def get_rapidgator_status():
    """
    현재 Rapidgator 세션 상태 확인
    """
    try:
        logger.info("Rapidgator 세션 상태 확인 요청")
        
        status_info = await rapidgator_client.get_session_status()
        
        return SessionStatusResponse(**status_info)
        
    except Exception as e:
        logger.error(f"세션 상태 확인 API 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"세션 상태 확인 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/rapidgator/logout")
async def logout_rapidgator():
    """
    Rapidgator 로그아웃 및 세션 정리
    """
    try:
        logger.info("Rapidgator 로그아웃 요청")
        
        success = await rapidgator_client.logout()
        
        if success:
            return {
                "success": True,
                "message": "Rapidgator 로그아웃 완료"
            }
        else:
            return {
                "success": False,
                "message": "로그아웃 중 문제가 발생했습니다"
            }
            
    except Exception as e:
        logger.error(f"로그아웃 API 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"로그아웃 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/rapidgator/test-login")
async def test_rapidgator_login():
    """
    환경변수의 크레덴셜로 Rapidgator 로그인 테스트
    """
    try:
        logger.info("Rapidgator 로그인 테스트 요청")
        
        # 환경변수 크레덴셜로 로그인 시도
        success = await rapidgator_client.ensure_logged_in()
        
        if success:
            session_status = await rapidgator_client.get_session_status()
            return {
                "success": True,
                "message": "Rapidgator 로그인 테스트 성공",
                "session_info": session_status
            }
        else:
            return {
                "success": False,
                "message": "Rapidgator 로그인 테스트 실패 - 환경변수 크레덴셜을 확인해주세요"
            }
            
    except Exception as e:
        logger.error(f"로그인 테스트 API 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"로그인 테스트 중 오류가 발생했습니다: {str(e)}"
        ) 