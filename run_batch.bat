@echo off
rem ===========================================================================
rem  Crawl ONE university batch (50 universities) to completion.
rem
rem  Usage:   run_batch.bat 1        (universities 001-050)
rem           run_batch.bat 2        (universities 051-100)
rem           ...
rem           run_batch.bat 6        (universities 251-272, 22 universities)
rem
rem  Batches share one crawl state + one output folder (uk_university/), so
rem  run them ONE AFTER ANOTHER. Each batch only crawls its own universities;
rem  already-scraped programmes are never fetched twice (resume log).
rem  Progress is appended to crawl_run.log.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
call .venv\Scripts\activate.bat

if "%~1"=="" (
  echo Usage: run_batch.bat ^<batch-number 1-6^>
  echo   1 = universities 001-050,  2 = 051-100, ...  6 = 251-272
  exit /b 2
)
set /a BN=%~1
if %BN% LSS 1 goto bad
if %BN% GTR 6 goto bad

rem zero-pad the batch number to match batches\batch_NN.txt
set PAD=0%BN%
set PAD=%PAD:~-2%
set BATCHFILE=batches\batch_%PAD%.txt
if not exist "%BATCHFILE%" (
  echo [ERROR] missing %BATCHFILE% - run make_batches.py first
  exit /b 2
)

set DELAY=4
set PASS_SECONDS=21600
set PASS_GAP_SECONDS=900

echo [%date% %time%] === BATCH %BN% start (%BATCHFILE%) >> crawl_run.log
echo Crawling batch %BN% from %BATCHFILE% - watch crawl_run.log

:loop
python scrape.py --input "%BATCHFILE%" --delay %DELAY% --max-runtime %PASS_SECONDS% --programs-only --split-by-university >> crawl_run.log 2>&1
if errorlevel 2 goto fail

rem --stats exit 0 = nothing left in the shared queue -> this batch is done
python scrape.py --stats --input "%BATCHFILE%" --jsonl programs.jsonl >> crawl_run.log 2>&1
if not errorlevel 1 goto done

echo [%date% %time%] batch %BN%: more work left - waiting 15 minutes before the next pass... >> crawl_run.log
timeout /t %PASS_GAP_SECONDS% /nobreak >nul
goto loop

:done
echo [%date% %time%] === BATCH %BN% COMPLETE === >> crawl_run.log
echo Batch %BN% complete. Next: run_batch.bat %BN%+1   (or run_all_batches.bat for all)
exit /b 0

:bad
echo Usage: run_batch.bat ^<batch-number 1-6^>
exit /b 2

:fail
echo [%date% %time%] === BATCH %BN% FAILED - check crawl_run.log / errors.jsonl, then re-run this batch === >> crawl_run.log
exit /b 1
