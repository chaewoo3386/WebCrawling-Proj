@echo off
REM 리뷰 감성 분석 Streamlit 앱 실행 스크립트
REM aiservice26 conda 환경의 python으로 streamlit 실행

set PY=C:\Users\user\anaconda3\envs\aiservice26\python.exe

cd /d "%~dp0"
"%PY%" -m streamlit run "%~dp0sentiment_app.py"

pause
