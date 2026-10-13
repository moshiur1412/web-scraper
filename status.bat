@echo off
rem ===========================================================================
rem  Progress report (no fetching, safe to run any time, even while crawling):
rem    - how many programme records exist and how many universities
rem    - how many URLs are known / done / still to fetch
rem    - top 10 universities by record count
rem  Exit code: 0 = everything scraped, 1 = work still left.
rem ===========================================================================
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] no .venv found - do the setup first, see README section 2.
  exit /b 2
)
call .venv\Scripts\activate.bat

python scrape.py --stats --input urls.txt --jsonl programs.jsonl
set RESULT=%errorlevel%

echo.
if "%RESULT%"=="0" (echo Crawl FINISHED - nothing left to fetch.) else (echo Crawl NOT finished yet - work remaining.)
echo (also see: uk_university\index.json  and  crawl_run.log)

rem keep the window open when double-clicked
echo %cmdcmdline% | findstr /i /c:"/c " >nul
if not errorlevel 1 pause
exit /b %RESULT%
