@echo off
rem ===========================================================================
rem  Crawl ONE university batch to completion.
rem
rem  Usage:   run_batch.bat 1        (first batch:  batches\batch_01.txt)
rem           run_batch.bat 2        (second batch: batches\batch_02.txt)
rem           ...
rem           run_batch.bat 7        (any batch you created - see README #5)
rem
rem  Batches share one crawl state + one output folder (uk_university/), so
rem  run them ONE AFTER ANOTHER (never in parallel). Each batch only crawls its
rem  own URLs; already-scraped programmes are never fetched twice (resume log).
rem  Progress is appended to crawl_run.log.
rem ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
call .venv\Scripts\activate.bat

if "%~1"=="" (
  echo Usage: run_batch.bat ^<batch-number^>
  echo   e.g. run_batch.bat 1        = crawl batches\batch_01.txt
  echo   List existing batches:  dir /b batches\batch_*.txt
  echo   New batch from a URL list:  create_batch.bat my_urls.txt
  exit /b 2
)

rem accept "1", "01", "007" ... (set /a would read 08/09 as octal -> strip zeros)
set "ARG=%~1"
if "%ARG:~0,1%"=="0" set "ARG=%ARG:~1%"
set /a BN=ARG 2>nul
if not defined BN goto bad
if %BN% LSS 1 goto bad

rem zero-pad the batch number to match batches\batch_NN.txt
set "PAD=%BN%"
if %BN% LSS 10 set "PAD=0%BN%"
set "BATCHFILE=batches\batch_%PAD%.txt"
if not exist "%BATCHFILE%" (
  echo [ERROR] %BATCHFILE% not found.
  echo         Existing batches:
  dir /b batches\batch_*.txt 2>nul
  echo         Make a new one:  create_batch.bat my_urls.txt
  echo         or:              python make_batches.py --input my_urls.txt
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
echo Batch %BN% complete.
echo Next:  dir /b batches\batch_*.txt   then   run_batch.bat ^<next number^>
echo        (run_all_batches.bat runs every remaining batch by itself)
exit /b 0

:bad
echo Usage: run_batch.bat ^<batch-number^>
exit /b 2

:fail
echo [%date% %time%] === BATCH %BN% FAILED - check crawl_run.log / errors.jsonl, then re-run this batch === >> crawl_run.log
exit /b 1
