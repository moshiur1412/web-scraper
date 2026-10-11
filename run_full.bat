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

set DELAY=2
set PASS_SECONDS=21600

:loop
echo [%date% %time%] === crawl pass === >> crawl_run.log
python scrape.py --input urls.txt --delay %DELAY% --max-runtime %PASS_SECONDS% --programs-only --split-by-university >> crawl_run.log 2>&1
if errorlevel 2 goto fail

python scrape.py --stats --input urls.txt --jsonl programs.jsonl >> crawl_run.log 2>&1
if not errorlevel 1 goto done

echo [%date% %time%] more work left - waiting 10 minutes before the next pass... >> crawl_run.log
timeout /t 600 /nobreak >nul
goto loop

:done
echo [%date% %time%] === CRAWL COMPLETE: every discovered programme has been scraped === >> crawl_run.log
exit /b 0

:fail
echo [%date% %time%] === CRAWL FAILED - check crawl_run.log / errors.jsonl, then run this again === >> crawl_run.log
exit /b 1
