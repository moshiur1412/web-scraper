@echo off
rem ===========================================================================
rem  Full UK crawl: every programme of all 272 UK universities on mastersportal.
rem  Resumable -- just run this again if the machine restarts; it stops on its
rem  own when nothing is left to fetch (checked with `scrape.py --stats`).
rem
rem  Usage:   run_full.bat          (output is appended to crawl_run.log)
rem ===========================================================================
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat

rem  Rate-limit friendly: ~4.5s/request (~15k pages/day), and each pass can sit
rem  through up to ~1.2h of 429 cooldowns before giving up on mastersportal.
set DELAY=4
set PASS_SECONDS=21600
set PASS_GAP_SECONDS=900

:loop
echo [%date% %time%] === crawl pass === >> crawl_run.log
python scrape.py --input urls.txt --delay %DELAY% --max-runtime %PASS_SECONDS% --programs-only --split-by-university >> crawl_run.log 2>&1
if errorlevel 2 goto fail

python scrape.py --stats --input urls.txt --jsonl programs.jsonl >> crawl_run.log 2>&1
if not errorlevel 1 goto done

echo [%date% %time%] more work left - waiting 15 minutes before the next pass... >> crawl_run.log
timeout /t %PASS_GAP_SECONDS% /nobreak >nul
goto loop

:done
echo [%date% %time%] === CRAWL COMPLETE: every discovered programme has been scraped === >> crawl_run.log
exit /b 0

:fail
echo [%date% %time%] === CRAWL FAILED - check crawl_run.log / errors.jsonl, then run this again === >> crawl_run.log
exit /b 1
