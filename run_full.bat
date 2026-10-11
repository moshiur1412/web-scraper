@echo off
rem ===========================================================================
rem  Full UK crawl: every programme of all 272 UK universities on mastersportal.
rem  Resumable -- just run this again if the machine restarts; it stops on its
rem  own when nothing is left to fetch (checked with `scrape.py --stats`).
rem
rem  Usage (inside the activated venv):   run_full.bat
rem ===========================================================================
setlocal
set DELAY=2
set PASS_SECONDS=21600

:loop
echo [%date% %time%] === crawl pass ===
python scrape.py --input urls.txt --out programs.json --delay %DELAY% --max-runtime %PASS_SECONDS% --programs-only --group-by university
if errorlevel 2 goto fail

python scrape.py --stats --input urls.txt --jsonl programs.jsonl
if not errorlevel 1 goto done

echo [%date% %time%] more work left - waiting 10 minutes before the next pass...
timeout /t 600 /nobreak >nul
goto loop

:done
echo.
echo === CRAWL COMPLETE: every discovered programme has been scraped ===
exit /b 0

:fail
echo.
echo === CRAWL FAILED - check the log / errors.jsonl, then run this again ===
exit /b 1
